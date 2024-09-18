# ============================================================================
# Sets up environment variables
# ============================================================================
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=True)
load_dotenv(dotenv_path="../.env", override=True)

# ============================================================================
# Set up system Path
# ============================================================================
import sys
import os

sys.path.extend({*os.environ["PYTHONPATH"].split(":")} - set(sys.path))

# ============================================================================
# Begin configuration
# ============================================================================

import shutil
import pytest
import datasets
import ray
from tests.tsettings import *
from typing import Dict
from utils.IO import *
from datasets.readers import ExtractedSetReader, ProcessedSetReader
from settings import *
from tests.pytest_utils.discretization import prepare_discretizer_listfiles

collect_ignore = ['src/utils/IO.py']


def pytest_addoption(parser):
    parser.addoption("--no-cleanup", action="store_true", default=False)


def pytest_configure(config) -> None:
    os.environ["DEBUG"] = "0"

    if SEMITEMP_DIR.is_dir() and not config.getoption("--no-cleanup"):
        shutil.rmtree(str(SEMITEMP_DIR))

    for task_name in TASK_NAMES:
        tests_io(f"Loading preproceesing data for task {task_name}...", end="\r")
        datasets.load_data(chunksize=75835,
                           source_path=TEST_DATA_DEMO,
                           storage_path=SEMITEMP_DIR,
                           preprocess=True,
                           verbose=False,
                           task=task_name)
        tests_io(f"Done loading preprocessing data for task {task_name}")


@pytest.fixture(scope="function", autouse=True)
def cleanup():
    if ray.is_initialized():
        ray.shutdown()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))

    # Execution
    yield

    # Clean after execution
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    if ray.is_initialized():
        ray.shutdown()


@pytest.fixture(scope="session")
def extracted_reader() -> ExtractedSetReader:
    extract_reader = datasets.load_data(chunksize=75835,
                                        source_path=TEST_DATA_DEMO,
                                        storage_path=SEMITEMP_DIR,
                                        verbose=False)
    return extract_reader


@pytest.fixture(scope="session")
def subject_ids(extracted_reader: ExtractedSetReader) -> list:
    icu_history = extracted_reader.read_csv("icu_history.csv")
    subjects = icu_history["SUBJECT_ID"].astype(int).unique().tolist()
    return subjects


@pytest.fixture(scope="session")
def preprocessed_readers() -> Dict[str, ProcessedSetReader]:
    proc_reader = dict()
    for task_name in TASK_NAMES:
        proc_reader[task_name] = datasets.load_data(chunksize=75835,
                                                    source_path=TEST_DATA_DEMO,
                                                    storage_path=SEMITEMP_DIR,
                                                    preprocess=True,
                                                    task=task_name,
                                                    verbose=False)
    return proc_reader


@pytest.fixture(scope="session")
def engineered_readers() -> Dict[str, ProcessedSetReader]:
    eng_reader = dict()
    for task_name in set(TASK_NAMES) - {"MULTI"}:
        tests_io(f"Loading engineered reader for task {task_name}...", end="\r")
        eng_reader[task_name] = datasets.load_data(chunksize=75835,
                                                   source_path=TEST_DATA_DEMO,
                                                   storage_path=SEMITEMP_DIR,
                                                   engineer=True,
                                                   task=task_name,
                                                   verbose=True)
        tests_io(f"Done loading engineered reader for task {task_name}")
    return eng_reader


@pytest.fixture(scope="session")
def discretized_readers() -> Dict[str, ProcessedSetReader]:
    disc_reader = dict()
    for task_name in set(TASK_NAMES):
        tests_io(f"Loading discretized reader for task {task_name}...", end="\r")
        disc_reader[task_name] = datasets.load_data(chunksize=75835,
                                                    source_path=TEST_DATA_DEMO,
                                                    storage_path=SEMITEMP_DIR,
                                                    discretize=True,
                                                    task=task_name,
                                                    verbose=False)
        tests_io(f"Done loading discretized reader for task {task_name}")

    for task_name in ["DECOMP", "LOS"]:
        tests_io(f"Loading deep supervision discretized reader for task {task_name}...", end="\r")
        _ = datasets.load_data(chunksize=75835,
                               source_path=TEST_DATA_DEMO,
                               storage_path=SEMITEMP_DIR,
                               deep_supervision=True,
                               discretize=True,
                               task=task_name,
                               verbose=False)
        tests_io(f"Done loading deep supervision discretized reader for task {task_name}")
    return disc_reader


@pytest.fixture(scope="session")
def discretizer_listfiles() -> None:
    list_files = prepare_discretizer_listfiles(list(set(TASK_NAMES) - set(["MULTI"])))
    return list_files


def pytest_unconfigure(config) -> None:
    os.environ["DEBUG"] = "0"
    if SEMITEMP_DIR.is_dir() and not config.getoption("--no-cleanup"):
        shutil.rmtree(str(SEMITEMP_DIR))
