"""
This module provides the MIMICFeatureEngine class to process time series data from the MIMIC-III dataset, applying various feature engineering techniques and storing the processed data for downstream tasks.

Usage Examples
--------------
.. code-block:: python

    from pathlib import Path
    import json
    from datasets.readers import ProcessedSetReader
    from datasets.trackers import PreprocessingTracker
    from datasets.processors import MIMICFeatureEngine

    # Define the path to the dataset, storage, and configuration file
    dataset_path = Path("/path/to/extracted/dataset")
    storage_path = Path("/path/to/store/processed/data")

    # example file located at etc/engineering_config.json
    config_path = Path("/path/to/config.json")

    # Initialize the reader and tracker
    reader = ProcessedSetReader(dataset_path)
    tracker = PreprocessingTracker(storage_path)

    # Initialize the MIMICFeatureEngine for the LOS (length-of-stay) task
    # Tasks are IHM, DECOMP, LOS, PHENO
    feature_engine = MIMICFeatureEngine(
        config_dict=config_path,
        task="LOS",
        reader=reader,
        storage_path=storage_path,
        tracker=tracker,
        verbose=True
    )

    # Transform a subject
    subject_id = 12345
    X, y = feature_engine.transform_subject(subject_id)
    
    # Transform the entire dataset
    dataset = reader.read_samples(read_ids=True)
    X, y, t = feature_engine.transform_dataset(dataset)

    # Or transfrom the reader directly
    reader = feature_engine.transform_reader(reader)

    # Save the transformed data
    feature_engine.save_data()

"""

import numpy as np
import pandas as pd
import json
from typing import Dict, List, Tuple
from scipy.stats import skew
from numpy import random
from multiprocess import Manager
from datasets.readers import ProcessedSetReader
from datasets.writers import DataSetWriter
from utils.jsons import dict_subset
from utils.IO import *
from pathlib import Path
from datasets.trackers import PreprocessingTracker
from datasets.processors import AbstractProcessor


class MIMICFeatureEngine(AbstractProcessor):
    """
    This class processes time series data from the MIMIC-III dataset, applying various feature 
    engineering techniques and storing the processed data for downstream tasks.
    The feature engineering is sped up using multiprocessing.
    The features are engineered using min, max, mean, std, skew and len.

    Parameters
    ----------
    config_dict : Path
        The path to the configuration dictionary for feature engineering.
    task : str
        The task name, used to determine specific processing steps.
    reader : ProcessedSetReader, optional
        The reader object for reading batch data, by default None.
    storage_path : Path, optional
        The path where the processed data will be stored, by default None.
    tracker : PreprocessingTracker, optional
        The tracker object for keeping track of preprocessing steps, by default None.
    verbose : bool, optional
        If True, print verbose logs during processing, by default False.
    """

    def __init__(self,
                 config_dict: Path,
                 task: str,
                 reader: ProcessedSetReader = None,
                 storage_path: Path = None,
                 tracker: PreprocessingTracker = None,
                 verbose=False) -> None:

        self._operation_name = "feature engieneering"  # For printing
        self._operation_adjective = "engineered"
        self._storage_path = storage_path
        self._save_file_type = "hdf5"
        self._writer = (DataSetWriter(storage_path) if storage_path is not None else None)
        self._source_reader = reader
        if tracker is not None:
            self._tracker = tracker
        else:
            self._tracker = (PreprocessingTracker(Path(storage_path, "progress"))
                             if storage_path is not None else None)
        self._task = task
        self._save_as_samples = (True if task in ["IHM", "PHENO"]\
                                 else False)
        self._subsample_switch = {
            "first_percentage":
                lambda start_t, end_t, percentage: (start_t, start_t +
                                                    (end_t - start_t) * percentage / 100.0),
            "last_percentage":
                lambda start_t, end_t, percentage: (end_t -
                                                    (end_t - start_t) * percentage / 100.0, end_t)
        }

        self._lock = Manager().Lock()
        self._verbose = verbose

        with open(config_dict) as file:
            config_dict = json.load(file)
            self._sampler_combinations = config_dict["sampler_combinations"]
            self._impute_config = config_dict["channels"]
            self._channel_names = config_dict["channel_names"]

        # Tracking variables
        self._init_tracking_variables()

        self._X = dict()
        self._y = dict()

    @property
    def subjects(self) -> list:
        """
        Get the list of subject IDs available in the reader.

        Returns
        -------
        list
            A list of subject IDs.
        """
        return self._source_reader.subject_ids

    def _transform(self,
                   dataset: Tuple[Dict[int, Dict[int, pd.DataFrame]]],
                   return_timestamp=False,
                   return_tracking=False):
        """
        Save the engineered data to the storage path.

        If no subject IDs are specified, all the engineered data will be saved.

        Parameters
        ----------
        subject_ids : list, optional
            A list of subject IDs to save data for. If None, all data is saved. Default is None.
        """
        X_dict, y_dict = dataset["X"], dataset["y"]

        info_io(
            f"Engineering processed data:\n"
            f"Engineered subjects: {self._n_subjects}\n"
            f"Engineered stays: {self._n_stays}\n"
            f"Engineered samples: {self._n_samples}\n"
            f"Skipped subjects: {self._n_skip}",
            verbose=self._verbose)

        self._samples_processed = 0

        self._X = dict()
        self._y = dict()
        self._t = dict()
        tracking_info = dict()

        for subject_id in X_dict.keys():
            X_subject = X_dict[subject_id]
            y_subject = y_dict[subject_id]
            self._X[subject_id] = dict()
            self._y[subject_id] = dict()
            self._t[subject_id] = dict()
            tracking_info[subject_id] = dict()

            for stay_id in X_subject:
                X_df = X_subject[stay_id]
                y_df = y_subject[stay_id]

                X_ss, ys, ts = self._engineer_stay(X_df, y_df)
                X_ss, ys, ts = self._convert_feature_dtype(X_ss, ys, ts)
                self._X[subject_id][stay_id] = X_ss
                self._y[subject_id][stay_id] = np.atleast_2d(ys)
                self._t[subject_id][stay_id] = ts

                n_samples = len(ys)
                if n_samples and len(X_ss):
                    tracking_info[subject_id][stay_id] = n_samples
                    self._n_samples += n_samples
                    self._n_stays += 1
                else:
                    del self._X[subject_id][stay_id]
                    del self._y[subject_id][stay_id]
                    del self._t[subject_id][stay_id]

                info_io(
                    f"Engineering processed data:\n"
                    f"Engineered subjects: {self._n_subjects}\n"
                    f"Engineered stays: {self._n_stays}\n"
                    f"Engineered samples: {self._n_samples}\n"
                    f"Skipped subjects: {self._n_skip}",
                    flush_block=True,
                    verbose=self._verbose)

            tracking_info = self._update_tracking(subject_id, tracking_info)

        info_io(
            f"Engineering processed data:\n"
            f"Engineered subjects: {self._n_subjects}\n"
            f"Engineered stays: {self._n_stays}\n"
            f"Engineered samples: {self._n_samples}\n"
            f"Skipped subjects: {self._n_skip}",
            flush_block=True,
            verbose=self._verbose)
        return_list = [self._X, self._y]
        if return_timestamp:
            return_list.append(self._t)
        if return_tracking:
            return tuple(return_list), tracking_info
        return tuple(return_list), tracking_info

    def _engineer_stay(self, X_df: pd.DataFrame, y_df: pd.DataFrame):
        """
        Engineer features for a single ICU stay.

        This method applies feature engineering techniques to the data from a single ICU stay.

        Parameters
        ----------
        X_df : pd.DataFrame
            DataFrame containing the input data for the ICU stay.
        y_df : pd.DataFrame
            DataFrame containing the output data for the ICU stay.

        Returns
        -------
        tuple
            A tuple containing the engineered features, output data, and timestamps.
        """
        X_df = self._impute_categorical_data(X_df)
        Xs, ys, ts = self._read_timeseries_windows(X_df, y_df)

        (Xs, ys, ts) = self._shuffle([Xs, ys, ts])

        X_ss = list()
        ys = list(ys)
        ts = list(ts)

        for df in Xs:
            subsamples = [[
                self._channel_subsampler(df[column], *combination)
                for combination in self._sampler_combinations
            ]
                          for column in self._channel_names]
            # Iterating by channel name from config allows normalization
            # and ensures comparability to ground truth data from original dir

            engineered_features = [
                self._make_engineered_features(channel.values)
                for subsample in subsamples
                for channel in subsample
            ]

            X_ss.append(np.concatenate(engineered_features))

            self._samples_processed += 1

        return X_ss, ys, ts

    def _convert_feature_dtype(self, X, y, t):
        """Does nothing, need because of inheritance.
        """
        return X, y, t

    def _processor_specific_save_data(self):

        def create_df(data, file_name) -> pd.DataFrame:
            if file_name == "X":
                dfs = pd.DataFrame([([subject_id, stay_id] +
                                     np.squeeze(frame).tolist()) if len(np.squeeze(frame)) > 1 else
                                    ([subject_id, stay_id, float(frame)])
                                    for subject_id, subject_stays in data.items()
                                    for stay_id, frame in subject_stays.items()])

            elif file_name == "y":
                dfs = pd.DataFrame([([subject_id, stay_id] +
                                     frame.tolist()) if isinstance(frame.tolist(), list) else
                                    ([subject_id, stay_id, float(frame)])
                                    for subject_id, subject_stays in data.items()
                                    for stay_id, frame in subject_stays.items()])
            dfs = dfs.rename(columns={0: "subject_id", 1: "stay_id"})
            if not len(dfs):
                return
            return dfs

        def append_data(X: dict, y: dict):

            def append(dfs: pd.DataFrame, file_name: str):
                file = Path(self._storage_path, f"{file_name}.csv")
                if file.is_file():
                    dfs.to_csv(file, mode='a', header=False, index=False)
                else:
                    dfs.to_csv(file, index=False)

            X_df = create_df(X, "X")
            y_df = create_df(y, "y")
            if y_df is None or not len(y_df) or not len(X_df):
                return
            append(X_df, "X")
            append(y_df, "y")

        if self._save_as_samples:
            with self._lock:
                append_data(self._X, self._y)

    def _shuffle(self, data: List[tuple]) -> None:
        """
        Shuffle the data.
        """
        assert len(data) >= 2

        data = list(zip(*data))
        random.shuffle(data)
        data = list(zip(*data))

        return data

    def _impute_categorical_data(self, X):
        """
        Imputes specified columns to categorical data.

        This method replaces specified values in the input DataFrame with their categorical equivalents based on
        the impute configuration. It ensures that the specified columns are treated as categorical data types.
        """
        replace_dict = {'nan': np.nan}

        for channel in self._impute_config.keys():
            if 'values' in self._impute_config[channel].keys():
                replace_dict.update(self._impute_config[channel]['values'])

        # with pd.option_context('future.no_silent_downcasting', True):
        X = X.replace(replace_dict).astype(float)
        return X

    def _make_engineered_features(self, data):
        """
        Generate engineered features.

        This method generates engineered features from the input data using statistical functions such as min, max,
        mean, standard deviation, skewness, and length.
        """
        functions = [min, max, np.mean, np.std, skew, len]
        import warnings
        warnings.filterwarnings("error")

        if len(data) == 0:
            engineered_data = np.full((len(functions,)), np.nan)
        else:
            # !TODO DEBUGGING
            engineered_data = [
                fn(data) if fn is not skew or
                (len(data) > 1 and not all(i == data[0]
                                           for i in data) or fn is len) else
                np.nan  #TODO! This will fail and be 0 in Windows
                for fn in functions
            ]
            engineered_data = np.array(engineered_data, dtype=np.float32)

        return engineered_data

    def _channel_subsampler(self, Sr: pd.Series, sampler_function, percentage):
        """
        Subsample a time series channel.

        This method subsamples a time series channel based on specified time window percentage.
        For example this could mean first 25% or last 50% of the time series.
        It returns the subsampled series within the calculated time window.
        """
        Sr = Sr.dropna()

        if len(Sr) == 0:
            return pd.DataFrame()

        start_t = Sr.index[0]
        end_t = Sr.index[-1]

        sampled_start_t, sampled_end_t = self._subsample_switch[sampler_function](start_t, end_t,
                                                                                  percentage)

        return Sr[(Sr.index < sampled_end_t + 1e-6) & (Sr.index > sampled_start_t - 1e-6)]

    def _timeseries_subsampler(self, X: pd.DataFrame, sampler_function, percentage):
        """
        Subsample a time series DataFrame.

        This method subsamples the input DataFrame based on specified time window percentage.
        For example this could mean first 25% or last 50% of the time series.
        It returns a list of subsampled columns.
        """
        if len(X) == 0:
            data = np.full((6), np.nan)
        else:
            start_t = X.index[0]
            end_t = X.index[-1]

            sampled_start_t, sampled_end_t = self._subsample_switch[sampler_function](start_t,
                                                                                      end_t,
                                                                                      percentage)

            data = X[(X.index < sampled_end_t + 1e-6) & (X.index > sampled_start_t - 1e-6)]

            if len(data) == 0:
                data = pd.DataFrame(np.full((len(X,)), np.nan))

        return [data[channel] for channel in data]

    def _read_timeseries_windows(self, X_df: pd.DataFrame, y_df: pd.DataFrame) -> 'tuple[list]':
        """
        Read time series windows.

        This method reads the time series data to create windows for feature engineering, reaching from the
        start time-stamp to the current timestamp. The window is paired with the current label. 
        """
        Xs = list()
        ys = list()
        ts = list()

        for i in range(len(y_df)):
            index = i

            if index < 0 or index >= len(y_df):
                raise ValueError(
                    "Index must be from 0 (inclusive) to number of examples (exclusive).")

            t = y_df.reset_index().iloc[index, 0]
            y = y_df.reset_index().iloc[index, 1:]
            X = X_df[X_df.index < t + 1e-6]

            Xs.append(X)
            ys.append(y)
            ts.append(t)

        return Xs, ys, ts

    def _convert_feature_dtype(self, X, y, t):
        """
        Convert feature data types.

        This method converts the data types of the input features, target values, and timestamps to numpy arrays.
        """
        X = np.stack(X)
        return np.array(X), np.array(y), np.array(t)
