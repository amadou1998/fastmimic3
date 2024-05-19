import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pickle
from models.trackers import ModelHistory, LocalModelHistory
from torch.utils.data import DataLoader
from collections import defaultdict
from pathlib import Path
from tensorflow.keras.utils import Progbar
from utils.IO import *
from .mappings import *


class LSTMNetwork(nn.Module):

    def __init__(self,
                 layer_size,
                 dropout_rate,
                 input_dim,
                 bidirectional=False,
                 recurrent_dropout=0.,
                 task=None,
                 target_repl=False,
                 output_dim=1,
                 depth=1,
                 model_path=None):
        super(LSTMNetwork, self).__init__()
        self._model_path = model_path
        if self._model_path is not None:
            # Persistent history
            self._model_path.mkdir(parents=True, exist_ok=True)
            self._history = ModelHistory(Path(self._model_path, "history"))
        else:
            # Mimics the storable
            self._history = LocalModelHistory()
        self.layer_size = layer_size
        self.dropout_rate = dropout_rate
        self.recurrent_dropout = recurrent_dropout
        self.depth = depth
        self.bidirectional = bidirectional

        final_activation = {
            "DECOMP": nn.Sigmoid(),
            "IHM": nn.Sigmoid(),
            "LOS": nn.Softmax(dim=-1),
            "PHENO": nn.Softmax(dim=-1),
            None: nn.Softmax(dim=-1) if output_dim != 1 else None
        }

        num_classes = {"DECOMP": 1, "IHM": 1, "LOS": 10, "PHENO": 25, None: output_dim}

        self.num_classes = num_classes[task]
        self.final_activation = final_activation[task]

        if isinstance(layer_size, int):
            self.hidden_sizes = [layer_size] * depth
        else:
            self.hidden_sizes = layer_size

        self.lstm_layers = nn.ModuleList()
        input_size = input_dim
        for i, hidden_size in enumerate(self.hidden_sizes):
            self.lstm_layers.append(
                nn.LSTM(input_size=input_size,
                        hidden_size=hidden_size,
                        num_layers=1,
                        batch_first=True,
                        dropout=(recurrent_dropout if i < depth - 1 else 0),
                        bidirectional=bidirectional))
            input_size = hidden_size * (2 if bidirectional else 1)

        self.dropout = nn.Dropout(dropout_rate)
        self.output_layer = nn.Linear(input_size, self.num_classes)

    @property
    def optimizer(self):
        if hasattr(self, "_optimizer"):
            return self._optimizer

    @property
    def loss(self):
        if hasattr(self, "_loss"):
            return self._loss

    def save(self, epoch):
        """_summary_
        """
        if self._model_path is not None:
            checkpoint_path = Path(self._model_path, f"cp-{epoch:04}.ckpt")
            torch.save(self.state_dict(), checkpoint_path)

    def load(self, epochs: int, weights_only=False):
        """_summary_

        Returns:
            _type_: _description_
        """
        if self._model_path is not None:
            latest_epoch = self._latest_epoch(epochs, self._model_path)
            if weights_only:
                checkpoint_path = Path(self._model_path, f"cp-{latest_epoch:04}.ckpt")
                if checkpoint_path.is_file():
                    model_state = torch.load(checkpoint_path)
                    self.load_state_dict(model_state)
                    print(f"Loaded model parameters from {checkpoint_path}")
                    return 1
            else:
                checkpoint_path = Path(self._model_path, f"cp-{latest_epoch:04}.pkl")
                if checkpoint_path.is_file():
                    with open(checkpoint_path, "rb") as load_file:
                        load_params = pickle.load(load_file)
                    for key, value in load_params.items():
                        setattr(self, key, value)
                    print(f"Loaded model from {checkpoint_path}")

                    return 1
        return 0

    def _clean_directory(self, best_epoch: int, epochs: int, keep_latest: bool = True):
        """_summary_

        Args:
            best_epoch (int): _description_
            keep_latest (bool, optional): _description_. Defaults to True.
        """

        [
            folder.unlink()
            for i in range(epochs + 1)
            for folder in self._model_path.iterdir()
            if f"{i:04d}" in folder.name and ((i != epochs) or not keep_latest) and
            (i != best_epoch) and (".ckpt" in folder.name) and folder.is_file()
        ]

    def forward(self, x):
        x.to(self._device)
        # Masking is not natively supported in PyTorch LSTM, assume x is already preprocessed if necessary
        for lstm in self.lstm_layers:
            x, _ = lstm(x)
            x = self.dropout(x)
        x = x[:, -1, :]
        x = self.output_layer(x)
        if self.final_activation:
            x = self.final_activation(x)
        return x

    def compile(self, optimizer=None, loss=None, class_weight=None):
        if isinstance(optimizer, str):
            if optimizer in optimizer_mapping:
                self._optimizer = optimizer_mapping[optimizer](self.parameters(), lr=0.001)
            else:
                raise ValueError(f"Optimizer {optimizer} not supported."
                                 f"Supported optimizers are {optimizer_mapping.keys()}")
        elif optimizer is None:
            self._optimizer = optim.Adam(self.parameters(), lr=0.001)
        else:
            self._optimizer = optimizer

        if isinstance(loss, str):
            if loss in loss_mapping:
                self._loss = loss_mapping[loss](weight=class_weight)
            else:
                raise ValueError(f"Loss {loss} not supported."
                                 f"Supported losses are {loss_mapping.keys()}")
        elif loss is None:
            self._loss = nn.CrossEntropyLoss(weight=class_weight)
        else:
            self._loss = loss
        self._device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.to(self._device)

    def _latest_epoch(self, epochs: int, filepath: Path):
        """_summary_

        Returns:
            _type_: _description_
        """
        if self._model_path is None:
            return 0
        check_point_epochs = [
            i for i in range(epochs + 1) for folder in filepath.iterdir()
            if f"{i:04d}" in folder.name
        ]

        if check_point_epochs:
            return max(check_point_epochs)

        return 0

    def _train(self,
               train_generator: DataLoader,
               epoch: int = 0,
               epochs: int = 1,
               sample_weights: dict = None,
               has_val: bool = False):
        print(f'\nEpoch {epoch}/{epochs}')
        self.train()
        train_losses = []
        generator_size = len(train_generator)
        self._train_progbar = Progbar(generator_size)

        for batch_idx, (inputs, labels) in enumerate(train_generator):
            inputs = inputs.to(self._device)
            labels = labels.to(self._device)
            self._optimizer.zero_grad()
            outputs = self(inputs)
            if sample_weights is not None:
                loss = self._loss(outputs, labels, sample_weight=sample_weights)
            else:
                loss = self._loss(outputs, labels)
            loss.backward()
            self._optimizer.step()
            train_losses.append(loss.item())

            self._train_progbar.update(batch_idx + 1,
                                       values=[('loss', loss.item())],
                                       finalize=(batch_idx == generator_size and not has_val))

        avg_train_loss = np.mean(train_losses)
        self._history.train_loss[epoch] = avg_train_loss
        if self._history.best_train["loss"] > avg_train_loss:
            self._history.best_train["loss"] = avg_train_loss
            self._history.best_train["epoch"] = epoch

    def _evaluate(self,
                  val_generator: DataLoader,
                  val_frequency: int,
                  epoch: int,
                  is_test: bool = False):

        if val_generator is not None and (epoch) % val_frequency == 0:
            self.eval()
            val_losses = []
            with torch.no_grad():
                for val_inputs, val_labels in val_generator:
                    val_inputs = val_inputs.to(self._device)
                    val_labels = val_labels.to(self._device)
                    val_outputs = self(val_inputs)
                    val_loss = self._loss(val_outputs, val_labels)
                    val_losses.append(val_loss.item())

            avg_val_loss = np.mean(val_losses)
            if is_test:
                self._history.test_loss = avg_val_loss
            else:
                self._history.val_loss[epoch] = avg_val_loss
                if self._history.best_val["loss"] > avg_val_loss:
                    self._history.best_val["loss"] = avg_val_loss
                    self._history.best_val["epoch"] = epoch
                if hasattr(self, "_train_progbar"):
                    self._train_progbar.update(self._train_progbar.target,
                                               values=[('loss', avg_val_loss),
                                                       ('val_loss', avg_val_loss)])
            return avg_val_loss

    def evaluate(self, test_generator: DataLoader):
        self._evaluate(val_generator=test_generator, val_frequency=0, epoch=0)

    def fit(self,
            train_generator: DataLoader,
            epochs: int,
            patience: int = None,
            save_best_only: bool = True,
            restore_best_weights: bool = True,
            sample_weights: dict = None,
            val_frequency: int = 1,
            val_generator: DataLoader = None,
            model_path: Path = None):
        if model_path is not None:
            self._model_path = model_path
            self._model_path.mkdir(parents=True, exist_ok=True)
        if patience is None:
            patience = epochs
        if val_generator is None:
            warn_io("WARNING:tensorflow:Early stopping conditioned on metric `val_loss` "
                    "which is not available. Available metrics are: loss")
        self._patience_counter = 0
        initial_epoch = self._latest_epoch(epochs, self._model_path)
        self.load(epochs, weights_only=True)

        for epoch in range(initial_epoch + 1, epochs + 1):

            self._train(train_generator=train_generator,
                        epoch=epoch,
                        epochs=epochs,
                        sample_weights=sample_weights,
                        has_val=val_generator is not None)

            self._evaluate(val_generator=val_generator, val_frequency=val_frequency, epoch=epoch)

            if val_generator is not None:
                best_epoch = self._history.best_val["epoch"]
            else:
                best_epoch = self._history.best_train["epoch"]
            if self._checkpoint(save_best_only=save_best_only,
                                restore_best_weights=restore_best_weights,
                                epoch=epoch,
                                epochs=epochs,
                                best_epoch=best_epoch,
                                patience=patience):
                break
        return self._history.to_json()

    def _checkpoint(self, save_best_only, restore_best_weights, epoch, epochs, best_epoch,
                    patience):
        if self._model_path is None:
            return False
        if save_best_only and best_epoch == epoch:
            self.save(epoch)
            self._clean_directory(best_epoch, epochs, True)
            self._patience_counter = 0
        elif not save_best_only and self._model_path is not None:
            self.save(epoch)
            self._patience_counter += 1
            if self._patience_counter >= patience:
                if restore_best_weights:
                    self.load_state_dict(
                        torch.load(Path(self._model_path, f"cp-{best_epoch:04}.ckpt")))
                return True

        return False


if __name__ == "__main__":
    from tests.settings import *
    import datasets
    from preprocessing.scalers import MIMICMinMaxScaler
    from generators.pytorch import TorchGenerator
    reader = datasets.load_data(chunksize=75836,
                                source_path=TEST_DATA_DEMO,
                                storage_path=SEMITEMP_DIR,
                                discretize=True,
                                time_step_size=1.0,
                                start_at_zero=True,
                                impute_strategy='previous',
                                task="IHM")

    reader = datasets.train_test_split(reader, test_size=0.2, val_size=0.1)

    from models.tf2.lstm import LSTMNetwork
    from tests.settings import *
    scaler = MIMICMinMaxScaler().fit_reader(reader.train)
    train_generator = TorchGenerator(reader=reader.train, scaler=scaler, batch_size=2, shuffle=True)
    val_generator = TorchGenerator(reader=reader.val, scaler=scaler, batch_size=2, shuffle=True)

    import torch
    import torch.nn as nn
    import torch.optim as optim

    from models.pytorch.lstm import LSTM
    model_path = Path(TEMP_DIR, "torch_lstm")
    model_path.mkdir(parents=True, exist_ok=True)
    model = LSTMNetwork(10,
                        0.2,
                        59,
                        bidirectional=False,
                        recurrent_dropout=0.,
                        task=None,
                        target_repl=False,
                        output_dim=1,
                        depth=2)  #,
    #model_path=model_path)

    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    model.compile(optimizer=optimizer, loss=criterion)
    # Example training loop
    history = model.fit(train_generator=train_generator, val_generator=val_generator, epochs=40)
    print(history)
