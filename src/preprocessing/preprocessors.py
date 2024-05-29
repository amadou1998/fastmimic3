"""Dataset file

This file allows access to the dataset as specified.

Todo:


YerevaNN/mimic3-benchmarks
"""
import numpy as np
import dateutil
import pandas as pd
from pathlib import Path
from multiprocess import Manager
from datasets.writers import DataSetWriter
from datasets.readers import ExtractedSetReader, ProcessedSetReader
from datasets.trackers import PreprocessingTracker
from utils import dict_subset
from utils.IO import *
from settings import *
from preprocessing import AbstractProcessor


class MIMICPreprocessor(AbstractProcessor):
    """_summary_
    """

    def __init__(self,
                 phenotypes_yaml: dict,
                 task: str,
                 label_type: str = "sparse",
                 reader: ExtractedSetReader = None,
                 tracker: PreprocessingTracker = None,
                 storage_path: Path = None,
                 verbose: bool = False):
        """_summary_ 
        TODO what is this source_path thing here

        Args:
            config_dict (_type_): _description_
            output_type (str, optional): _description_. Defaults to "sparse".
            task_path (str, optional): _description_. Defaults to "".
        """

        if label_type not in ["sparse", "one-hot"]:
            raise ValueError(f"Type must be one of {*['sparse', 'one-hot'],}")

        self._label_type = label_type
        self._storage_path = storage_path

        if task not in TASK_NAMES:
            raise ValueError(f"Task must be one of {*TASK_NAMES,}")

        self._task = task
        self._writer = (None if storage_path is None else DataSetWriter(self._storage_path))
        self._extracted_set_reader = reader  # the set we are trying to read from
        if tracker is not None:
            self._tracker = tracker
        else:
            self._tracker = (None if storage_path is None else PreprocessingTracker(
                Path(storage_path, "progress")))
        self._processed_set_reader = (None if storage_path is None else ProcessedSetReader(
            root_path=storage_path))
        self._lock = Manager().Lock()
        self._phenotypes_yaml = phenotypes_yaml
        self._verbose = verbose

    @property
    def subjects(self) -> list:
        """_summary_

        Returns:
            list: _description_
        """
        if self._extracted_set_reader is None:
            return []
        return self._extracted_set_reader.subject_ids

    def transform_subject(self, subject_id: int) -> None:
        """_summary_

        Args:
            subject_id (_type_): _description_

        Returns:
            _type_: _description_
        """
        subject_data = self._extracted_set_reader.read_subject(subject_id, read_ids=True)
        if not subject_data:
            return None, None
        del subject_data["subject_events"]
        X, y = self.transform({subject_id: subject_data})
        if not X or not y:
            return None, None
        if self._tracker is None:
            return X, y
        with self._lock:
            tracking_info = self._tracker.subjects[subject_id]
        return (X, y), tracking_info

    def transform(self, dataset: dict):
        """_summary_

        Args:
            timeseries (_type_): _description_
            episodic_data (_type_): _description_
            diagnoses (_type_): _description_
            icuhistory (_type_): _description_
            task (_type_): _description_
            task_path (_type_, optional): _description_. Defaults to None.

        Returns:
            _type_: _description_
        """
        self._X = dict()
        self._y = dict()

        # Tracking variables
        n_subjects = 0
        n_stays = 0
        n_skip = 0
        n_samples = 0

        start_verbose = True

        if self._task in ["LOS"] and self._label_type == "one-hot":
            info_io(f"Only sparse output_type is available for task {self._task}!"
                    f" Argument {self._label_type} disregarded")
            self._label_type = "sparse"

        for subject, subject_data in dataset.items():
            skip_subject = False

            subject_timeseries: pd.DataFrame = subject_data['timeseries']
            diagnoses_df: pd.DataFrame = subject_data['subject_diagnoses']
            icuhistory_df: pd.DataFrame = subject_data['subject_icu_history']
            episodic_data_df: pd.DataFrame = subject_data['episodic_data']

            self._X[subject] = dict()
            self._y[subject] = dict()

            tracking_info = dict()

            if (self._tracker is not None) and \
               (subject in self._tracker.subjects) and \
               (not self._X[subject]):
                # Do not reprocess already existing directories
                self._X[subject], self._y[subject] = self._processed_set_reader.read_sample(
                    str(subject), read_ids=True).values()
                skip_subject = True
                continue
            elif start_verbose:
                if self._verbose:
                    info_io(f"Processing timeseries data:\n"
                            f"Processed subjects: {0}\n"
                            f"Processed stays: {0}\n"
                            f"Processed samples: {0}\n"
                            f"Skipped subjects: {0}")
                    start_verbose = False

            for icustay in subject_timeseries:
                stay_timeseries_df = subject_timeseries[icustay]
                cur_episodic_data_df = episodic_data_df.loc[icustay]
                cur_icuhistory_sr = icuhistory_df.reset_index().set_index("ICUSTAY_ID").loc[icustay]

                if not pd.isna(cur_episodic_data_df["MORTALITY"]):
                    mortality = int(cur_episodic_data_df["MORTALITY"])
                else:
                    continue

                if self._task == "IHM":
                    self._X[subject][icustay], self._y[subject][
                        icustay] = self.make_inhospital_mortality_data(
                            stay_timeseries_df, cur_episodic_data_df, mortality)

                elif self._task == "DECOMP":
                    self._X[subject][icustay], self._y[subject][
                        icustay] = self.make_decompensation_data(stay_timeseries_df,
                                                                 cur_episodic_data_df,
                                                                 cur_icuhistory_sr)
                elif self._task == "LOS":
                    self._X[subject][icustay], self._y[subject][
                        icustay] = self.make_length_of_stay_data(stay_timeseries_df,
                                                                 cur_episodic_data_df)
                elif self._task == "PHENO":
                    stay_diagnoses_df = diagnoses_df[diagnoses_df['ICUSTAY_ID'] == icustay]
                    self._X[subject][icustay], self._y[subject][
                        icustay] = self.make_pheontyping_data(stay_timeseries_df,
                                                              cur_episodic_data_df,
                                                              stay_diagnoses_df,
                                                              self._phenotypes_yaml)
                else:
                    raise ValueError(
                        "Task must be one of: in_hospital_mortality, decompensation, length_of_stay, phenotyping"
                    )
                if self._y[subject][icustay].empty:
                    del self._y[subject][icustay]
                    del self._X[subject][icustay]
                    continue
                else:
                    tracking_info[icustay] = len(self._y[subject][icustay])
                    n_stays += 1
                    n_samples += len(self._y[subject][icustay])
                    if self._verbose:
                        info_io(
                            f"Processing timeseries data:\n"
                            f"Processed subjects: {n_subjects}\n"
                            f"Processed stays: {n_stays}\n"
                            f"Processed samples: {n_samples}\n"
                            f"Skipped subjects: {n_skip}",
                            flush_block=True)

            if skip_subject:
                continue

            if self._tracker is not None and tracking_info:
                with self._lock:
                    self._tracker.subjects.update({subject: tracking_info})

            if not len(self._y[subject]) or not len(self._X[subject]):
                del self._y[subject]
                del self._X[subject]
                n_skip += 1
            else:
                n_subjects += 1
        if self._verbose:
            info_io(
                f"Processing timeseries data:\n"
                f"Processed subjects: {n_subjects}\n"
                f"Processed stays: {n_stays}\n"
                f"Processed samples: {n_samples}\n"
                f"Skipped subjects: {n_skip}",
                flush_block=True)

        return self._X, self._y

    def save_data(self, subjects: list = None) -> None:
        """_summary_

        Args:
            task_path (_type_, optional): _description_. Defaults to None.
        """
        if self._writer is None:
            info_io("No storage path provided. Data will not be saved.")
            return
        with self._lock:
            if subjects is None:
                self._writer.write_bysubject({"X": self._X})
                self._writer.write_bysubject({"y": self._y})
            else:
                self._writer.write_bysubject({"X": dict_subset(self._X, subjects)})
                self._writer.write_bysubject({"y": dict_subset(self._y, subjects)})

        return

    def make_inhospital_mortality_data(self, timeseries_df: pd.DataFrame,
                                       episodic_data_df: pd.DataFrame, mortality: int):
        """_summary_

        Args:
            timeseries_df (_type_): _description_
            mortality (_type_): _description_

        Returns:
            _type_: _description_
        """
        precision = IHM_SETTINGS['sample_precision']
        label_start_time = IHM_SETTINGS['label_start_time']
        los = 24.0 * episodic_data_df.loc['LOS']  # in hours
        if los < label_start_time:
            return pd.DataFrame(columns=timeseries_df.columns), \
                   pd.DataFrame(columns=['Timestamp', 'y']).set_index('Timestamp')
        X: pd.DataFrame = timeseries_df[(timeseries_df.index < label_start_time + precision)
                                        & (timeseries_df.index > -precision)]
        if X.empty:
            return X, pd.DataFrame(columns=['Timestamp', 'y'])

        y = np.array([(X.index[-1], mortality)])
        y = pd.DataFrame(y, columns=['Timestamp', 'y']).set_index('Timestamp')

        return X, y

    def make_decompensation_data(self, timeseries_df: pd.DataFrame, episodic_data_df: pd.DataFrame,
                                 icu_stay):
        """_summary_

        Args:
            timeseries_df (_type_): _description_
            episodic_data_df (_type_): _description_
            icuhistory_df (_type_): _description_

        Returns:
            _type_: _description_
        """
        precision = DECOMP_SETTINGS['sample_precision']
        sample_rate = DECOMP_SETTINGS['sample_rate']
        label_start_time = DECOMP_SETTINGS['label_start_time']
        future_time_interval = DECOMP_SETTINGS['future_time_interval']
        # future_time_interval is Hours in which the preson will have to be dead for label to be 1

        mortality = int(episodic_data_df.loc["MORTALITY"])

        los = 24.0 * episodic_data_df.loc['LOS']  # in hours

        deathtime = icu_stay['DEATHTIME']
        intime = icu_stay['INTIME']

        if pd.isnull(deathtime):
            lived_time = 1e18
        else:
            if isinstance(icu_stay['DEATHTIME'], str):
                deathtime = dateutil.parser.parse(deathtime)
            if isinstance(icu_stay['INTIME'], str):
                intime = dateutil.parser.parse(intime)
            lived_time = (deathtime - intime).total_seconds() / 3600.0

        X: pd.DataFrame = timeseries_df[(timeseries_df.index < los + precision)
                                        & (timeseries_df.index > -precision)]
        if X.empty:
            return X, pd.DataFrame(columns=['Timestamp', 'y']).set_index('Timestamp')

        event_times = timeseries_df.index[(timeseries_df.index < los + precision)
                                          & (timeseries_df.index > -precision)]

        sample_times = np.arange(0.0, min(los, lived_time) + precision, sample_rate)
        sample_times = list(filter(lambda x: x > label_start_time, sample_times))

        # At least one measurement
        sample_times = list(filter(lambda x: x > event_times[0], sample_times))

        y = list()

        for hour in sample_times:
            if mortality == 0:
                cur_mortality = 0
            else:
                cur_mortality = int(lived_time - hour < future_time_interval)
            y.append((hour, cur_mortality))

        if not y:
            return pd.DataFrame(columns=X.columns), pd.DataFrame(columns=['Timestamp', 'y'])

        y = pd.DataFrame(y, columns=['Timestamp', 'y']).set_index('Timestamp')

        return X, y

    def make_length_of_stay_data(self, timeseries_df: pd.DataFrame, episodic_data_df: pd.DataFrame):
        """_summary_

        Args:
            timeseries_df (_type_): _description_
            episodic_data_df (_type_): _description_

        Returns:
            _type_: _description_
        """
        precision = LOS_SETTINGS['sample_precision']
        sample_rate = LOS_SETTINGS['sample_rate']
        label_start_time = LOS_SETTINGS['label_start_time']
        bins = LOS_SETTINGS['bins']

        los = 24.0 * episodic_data_df.loc['LOS']  # in hours

        X: pd.DataFrame = timeseries_df[(timeseries_df.index < los + precision)
                                        & (timeseries_df.index > -precision)]
        if X.empty:
            return X, pd.DataFrame(columns=['Timestamp', 'y']).set_index('Timestamp')

        event_times = timeseries_df.index[(timeseries_df.index < los + precision)
                                          & (timeseries_df.index > -precision)]

        sample_times = np.arange(0.0, los + precision, sample_rate)
        sample_times = list(filter(lambda x: x > label_start_time, sample_times))
        sample_times = list(filter(lambda x: x > event_times[0], sample_times))

        y = list()

        for hour in sample_times:
            if self._label_type == "one-hot":
                category_index = np.digitize(los - hour, bins) - 1
                remaining_los = [0] * 10
                remaining_los[category_index] = 1
                y.append((hour, remaining_los))

            elif self._label_type == "sparse":
                y.append((hour, los - hour))

        y = pd.DataFrame(y, columns=['Timestamp', 'y']).set_index('Timestamp')
        if y.empty:
            # Will prevent the sample from being used
            return pd.DataFrame(columns=X.columns), y

        return X, y

    def make_pheontyping_data(self, timeseries_df: pd.DataFrame, episodic_data_df: pd.DataFrame,
                              diagnoses_df: pd.DataFrame, phenotypes_yaml: pd.DataFrame):
        """_summary_

        Args:
            timeseries_df (_type_): _description_
            episodic_data_df (_type_): _description_
            diagnoses_df (_type_): _description_
            phenotypes_yaml (_type_): _description_

        Returns:
            _type_: _description_
        """
        precision = PHENOT_SETTINGS['sample_precision']
        valid_ids = PHENOT_SETTINGS['valid_ids']

        los = 24.0 * episodic_data_df.loc['LOS']  # in hours
        X: pd.DataFrame = timeseries_df[(timeseries_df.index < los + precision)
                                        & (timeseries_df.index > -precision)]
        if X.empty:
            return X, pd.DataFrame(columns=['Timestamp', 'y']).set_index('Timestamp')

        # Dictionary mapping codes to groups
        code_to_group = {}
        for group in phenotypes_yaml:
            codes = phenotypes_yaml[group]['codes']
            for code in codes:
                if code not in code_to_group:
                    code_to_group[code] = group
                else:
                    assert code_to_group[code] == group

        # index is ID of phenotype in the yaml
        id_to_group = sorted(phenotypes_yaml.keys())
        group_to_id = dict((x, i) for (i, x) in enumerate(id_to_group))

        # Index is pheontype designation and item is id
        cur_labels = [0] * len(id_to_group)

        for index, row in diagnoses_df.iterrows():
            if row['USE_IN_BENCHMARK']:
                code = row['ICD9_CODE']
                group = code_to_group[code]
                group_id = group_to_id[group]
                cur_labels[group_id] = 1

        # Only use in benchmark = True labels
        if not valid_ids:
            valid_ids = [
                i for (i, x) in enumerate(cur_labels)
                if phenotypes_yaml[id_to_group[i]]['use_in_benchmark']
            ]
            PHENOT_SETTINGS['valid_ids'] = valid_ids

        cur_labels = [cur_labels[index] for index in valid_ids]

        y = [los] + cur_labels
        y = pd.DataFrame((y,), columns=["Timestamp"] + [f"y{i}" for i in range(len(y) - 1)])
        y = y.set_index('Timestamp')

        return X, y
