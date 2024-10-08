"""
Dataset Writers
===============

This module provides classes and methods for writing dataset files, and creating the subject 
directories named with the respecitve subject ID. The main class `DataSetWriter`
is used to write the subject data either as .npy, .csv, or .hdf5 files. 
and ICU history.



References
----------
- YerevaNN/mimic3-benchmarks: https://github.com/YerevaNN/mimic3-benchmarks
"""
import warnings
import shutil
import pandas as pd
import numpy as np
from pathos.helpers import mp
import operator
from pathlib import Path
from utils.types import NoopLock
from utils.IO import *
from functools import reduce

__all__ = ["DataSetWriter"]


class DataSetWriter():
    """
    A writer class for datasets, providing methods to write data to files and create subject ID labeld directories.

    Parameters
    ----------
    root_path : Path
        The root directory path where the dataset files will be written.

    Examples
    --------
    >>> root_path = Path("/path/to/data")
    >>> writer = DataSetWriter(root_path)
    >>> data = {
    ...     "subject_events": {10006: pd.DataFrame(...), 10011: pd.DataFrame(...)},
    ...     "episodic_data": {10006: pd.DataFrame(...), 10011: pd.DataFrame(...)}
    ... }
    >>> writer.write_bysubject(data, file_type="csv")
    """

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self._possible_filenames = [
            "episodic_data", "timeseries", "subject_events", "subject_diagnoses",
            "subject_icu_history", "X", "M", "y", "yds", "t", "header"
        ]

    def _check_filename(self, filename: str):
        """
        Check if the filename is valid.
        """
        if filename not in self._possible_filenames:
            raise ValueError(
                f"File name {filename} is invalid! Choose a filename from {self._possible_filenames}"
            )

    def _get_subject_ids(self, data: dict):
        """
        Get the subject IDs from the data dictionary.
        """

        id_sets = [set(dictionary.keys()) for dictionary in data.values()]
        subject_ids = list(reduce(operator.and_, id_sets))
        return subject_ids

    def _dynamic_file_type(self, subject_dir: Path):
        """
        Checks the file type of other files in the directory.
        If none defaults to csv.
        """
        for file in subject_dir.iterdir():
            if file.is_file():
                if file.suffix.strip(".") == "h5":
                    return "hdf5"
                return file.suffix.strip(".")
        return "csv"

    def write_bysubject(self,
                        data: dict,
                        index: bool = True,
                        append: bool = False,
                        file_type: str = "csv"):
        """
        Write data of file type by subject and create subject ID labeled directories.

        Parameters
        ----------
        data : dict
            The data to write.
        index : bool, optional
            Whether to write the index. Default is True.
        append : bool, optional
            Whether to overwrite existing files. Default is False.
        file_type : str, optional
            The file type to write. Must be one of ['csv', 'npy', 'hdf5']. Default is 'csv'.

        Raises
        ------
        ValueError
            If the file_type is not supported.
        """
        if self.root_path is None:
            return

        if not file_type in ["csv", "npy", "hdf5", "dynamic"]:
            raise ValueError(
                f"file_type {file_type} not supported. Must be one of ['csv', 'npy', 'hdf5', 'dynamic']"
            )

        for subject_id in self._get_subject_ids(data):

            self._write_subject(
                subject_id=subject_id,
                data={filename: data[filename][subject_id] for filename in data.keys()},
                index=index,
                append=append,
                file_type=file_type)

        return

    def _write_subject(self,
                       subject_id: int,
                       data: dict,
                       index: bool = True,
                       append: bool = False,
                       file_type: str = "csv"):
        """
        Write all files for a single subject
        """

        def save_df(df: pd.DataFrame,
                    path: Path,
                    index: str = True,
                    file_type: str = "csv",
                    append: bool = False) -> None:
            # Saving df with different file types and append modes
            if append and path.is_file() and not file_type == "hd5f":
                mode = "a"
                header = False
            else:
                mode = "w"
                header = True
            if file_type == "hdf5":
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=pd.io.pytables.PerformanceWarning)
                    pd.DataFrame(df).to_hdf(Path(path.parent, f"{path.stem}.h5"),
                                            key="data",
                                            mode=mode,
                                            index=index)
            elif file_type == "csv":
                pd.DataFrame(df).to_csv(Path(path.parent, f"{path.stem}.csv"),
                                        mode=mode,
                                        index=index,
                                        header=header)
            elif file_type == "npy":
                if isinstance(df, (pd.DataFrame, pd.Series)):
                    df = df.to_numpy()
                np.save(Path(path.parent, f"{path.stem}.npy"), df)
            else:
                raise ValueError(f"file_type {file_type} not supported")

        # --------------- parameter checks ---------------
        if file_type in ["npy", "hdf5"] and append:
            raise ValueError("Append mode not supported for numpy files!")

        if not file_type in ["csv", "npy", "hdf5", "dynamic"]:
            raise ValueError(f"file_type {file_type} not supported. Must be one"
                             " of ['csv', 'npy', 'hdf5', 'dynamic']")

        subject_path = Path(self.root_path, str(subject_id))
        if file_type == "dynamic":
            file_type = self._dynamic_file_type(subject_path)

        # ----------------- write files -----------------
        for filename, item in data.items():
            delet_flag = False
            self._check_filename(filename)

            if not subject_path.is_dir():
                subject_path.mkdir(parents=True, exist_ok=True)
            if isinstance(item, (pd.DataFrame, pd.Series, np.ndarray)):
                if not len(item):
                    continue
                csv_path = Path(subject_path, f"{filename}")
                save_df(df=item, path=csv_path, index=index, file_type=file_type, append=append)
            elif isinstance(item, dict):
                for icustay_id, data in item.items():
                    if not len(data):
                        continue
                    csv_path = Path(subject_path, f"{filename}_{icustay_id}")
                    save_df(df=data, path=csv_path, index=index, file_type=file_type, append=append)
            else:
                raise TypeError(
                    f"Object of type {type(item)} cannot be written using dataset writer\n"
                    "Should be one of dict, pd.DataFrame, pd.Series or np.ndarray")

            # do not create empty or incomplete folders
            if not [folder for folder in subject_path.iterdir()] or delet_flag:
                debug_io(f"Removing folder {subject_path}, because a "
                         "file is missing or the folder is empty!")
                shutil.rmtree(str(subject_path))

    def write_subject_events(self, data: dict, lock: mp.Lock = NoopLock(), dtypes: dict = None):
        """
        Write subject events data to files by creating a new file or appending to existing file and create subject ID labeled directories.

        Parameters
        ----------
        data : dict
            The subject events data to write.
        lock : mp.Lock, optional
            A lock object to synchronize writing. Default is None.
        dtypes : dict, optional
            Data types to cast the dataframe to. Default is None.
        """
        if self.root_path is None:
            return

        def write_csv(dataframe: pd.DataFrame, path: Path, lock: mp.Lock):
            if dataframe.empty:
                return
            with lock:
                if dtypes is not None:
                    dataframe = dataframe.astype(dtypes)
                if not path.is_file():
                    dataframe.to_csv(path, index=False)
                else:
                    dataframe.to_csv(path, mode='a', index=False, header=False)

            return

        for subject_id, subject_data in data.items():
            subject_path = Path(self.root_path, str(subject_id))
            subject_path.mkdir(parents=True, exist_ok=True)
            subject_event_path = Path(subject_path, "subject_events.csv")

            write_csv(subject_data, subject_event_path, lock)

        return
