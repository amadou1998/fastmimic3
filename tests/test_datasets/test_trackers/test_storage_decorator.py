import pytest
import shutil
from pathlib import Path
from utils.IO import *
from tests.tsettings import *
from storable import storable


@storable
class TestClass:
    num_samples: int = 0
    time_elapsed: float = 0.0
    finished: bool = False
    subjects: dict = {"a": 0, "b": 0}
    names: dict = {"a": "a", "b": "b"}


@storable
class CountTestClass:
    num_samples: int = 0
    time_elapsed: float = 0.0
    finished: bool = False
    subject_ids: list = list()
    subjects: dict = {"a": 0, "b": 0}
    _store_total: bool = True


# Test the storable
def test_storable_basics():
    tests_io("Test case basic capabilities of Storable.", level=0)

    # Test the default values
    assert TestClass.num_samples == 0
    assert TestClass.time_elapsed == 0.0
    assert TestClass.finished == False
    assert TestClass.subjects == {"a": 0, "b": 0}
    assert TestClass.names == {"a": "a", "b": "b"}

    # Test the correct recreation of its attributes with the correct types
    check_dtypes(TestClass)
    tests_io("Succeeded testing initialization.")

    # Test the storage path
    test_instance = TestClass(Path(TEMP_DIR, "progress"))

    assert Path(TEMP_DIR, "progress").is_file()

    # Test assignment
    test_instance.num_samples = 10
    test_instance.time_elapsed = 1.0
    test_instance.finished = True
    test_instance.subjects = {"a": 1, "b": 2}
    test_instance.names = {"a": "b", "b": "a"}

    assert test_instance.num_samples == 10
    assert test_instance.time_elapsed == 1.0
    assert test_instance.finished == True
    assert test_instance.subjects == {"a": 1, "b": 2}
    assert test_instance.names == {"a": "b", "b": "a"}

    check_dtypes(test_instance)
    tests_io("Succeeded testing assignment.")

    # Test restorable assignment
    del test_instance
    test_instance = TestClass(Path(TEMP_DIR, "progress"))

    assert test_instance.num_samples == 10
    assert test_instance.time_elapsed == 1.0
    assert test_instance.finished == True
    assert test_instance.subjects == {"a": 1, "b": 2}
    assert test_instance.names == {"a": "b", "b": "a"}

    check_dtypes(test_instance)

    tests_io("Succeeded testing restoration.")

    # Test __iadd__
    test_instance.num_samples += 10
    test_instance.time_elapsed += 1.1

    assert test_instance.num_samples == 20
    assert test_instance.time_elapsed == 2.1

    check_dtypes(test_instance)

    # Test restorable __iadd__
    del test_instance
    test_instance = TestClass(Path(TEMP_DIR, "progress"))

    assert test_instance.num_samples == 20
    assert test_instance.time_elapsed == 2.1
    check_dtypes(test_instance)

    tests_io("Succeeded testing __iadd__.")


def test_dictionary_iadd():
    tests_io("Test case dictionary iadd.", level=0)
    test_instance = TestClass(Path(TEMP_DIR, "progress"))
    test_instance.subjects == {"a": 0, "b": 0}

    test_instance.subjects += {"a": 1, "b": 2}
    assert test_instance.subjects == {"a": 1, "b": 2}

    test_instance.subjects += {"a": 1}
    assert test_instance.subjects == {"a": 2, "b": 2}

    tests_io("Succeeded testing numerical dictionary iadd.")

    # Test restorable dictionary iadd
    del test_instance
    test_instance = TestClass(Path(TEMP_DIR, "progress"))

    assert test_instance.subjects == {"a": 2, "b": 2}
    tests_io("Succeeded testing restoration of numerical dictionary iadd.")


def test_dictionary_update():
    tests_io("Test case dictionary update.", level=0)
    test_instance = TestClass(Path(TEMP_DIR, "progress"))
    test_instance.names = {"a": {"a": 1, "b": 1}, "b": {"a": 2, "b": 2}}
    test_instance.names.update({"a": {"c": 1, "d": 1}, "c": {"a": 1, "b": 1}})
    assert test_instance.names == {
        "a": {
            "a": 1,
            "b": 1,
            "c": 1,
            "d": 1
        },
        "b": {
            "a": 2,
            "b": 2
        },
        "c": {
            "a": 1,
            "b": 1
        }
    }
    tests_io("Succeeded testing dictionary update.")
    del test_instance
    test_instance = TestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.names == {
        "a": {
            "a": 1,
            "b": 1,
            "c": 1,
            "d": 1
        },
        "b": {
            "a": 2,
            "b": 2
        },
        "c": {
            "a": 1,
            "b": 1
        }
    }
    tests_io("Succeeded testing restoration of dictionary update.")


def test_total_count():
    # Only implemented for single nestation and not for iadd
    tests_io("Test case total count for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    test_instance.subjects = {"a": {"a": 1, "b": 2}, "b": {"a": 2, "b": 4}}
    assert test_instance.subjects == {
        "a": {
            "a": 1,
            "b": 2,
            "total": 3
        },
        "b": {
            "a": 2,
            "b": 4,
            "total": 6
        },
        "total": 9
    }
    tests_io("Succeeded dictionary assignment total count.")
    test_instance.subjects.update({"a": {"c": 3}})
    assert test_instance.subjects == {
        "a": {
            "a": 1,
            "b": 2,
            "c": 3,
            "total": 6
        },
        "b": {
            "a": 2,
            "b": 4,
            "total": 6
        },
        "total": 12
    }
    tests_io("Succeeded dictionary nested update total count.")

    test_instance.subjects = {"a": 0, "b": 0}
    assert test_instance.subjects == {"a": 0, "b": 0, "total": 0}
    tests_io("Succeeded dictionary reassignment total count.")

    test_instance.subjects = {}
    assert test_instance.subjects == {"total": 0}
    tests_io("Succeeded dictionary empty reassignment total count.")

    test_instance.subjects.update({"a": 1, "b": 2})
    assert test_instance.subjects == {"a": 1, "b": 2, "total": 3}
    tests_io("Succeeded dictionary simple data type overwrite total count.")

    test_instance.subjects.update({"a": 1, "b": 1})
    assert test_instance.subjects == {"a": 1, "b": 1, "total": 2}

    test_instance.subjects.update({"a": 2, "b": 2})
    assert test_instance.subjects == {"a": 2, "b": 2, "total": 4}

    test_instance.subjects.update({"c": 1, "d": 1})
    assert test_instance.subjects == {"a": 2, "b": 2, "c": 1, "d": 1, "total": 6}

    test_instance.subjects.update({"a": {"a": 1, "b": 2}, "b": {"a": 2, "b": 4}})
    assert test_instance.subjects == {
        "a": {
            "a": 1,
            "b": 2,
            "total": 3
        },
        "b": {
            "a": 2,
            "b": 4,
            "total": 6
        },
        "c": 1,
        "d": 1,
        "total": 11
    }
    tests_io("Succeeded dictionary complex data type overwrite total count.")
    test_instance.subjects.update({"c": 3})
    assert test_instance.subjects == {
        "a": {
            "a": 1,
            "b": 2,
            "total": 3
        },
        "b": {
            "a": 2,
            "b": 4,
            "total": 6
        },
        "c": 3,
        "d": 1,
        "total": 13
    }

    test_instance.subjects.update({"d": {"a": 1, "b": 1}})
    assert test_instance.subjects == {
        "a": {
            "a": 1,
            "b": 2,
            "total": 3
        },
        "b": {
            "a": 2,
            "b": 4,
            "total": 6
        },
        "c": 3,
        "d": {
            "a": 1,
            "b": 1,
            "total": 2
        },
        "total": 14
    }


def test_list_basic():
    tests_io("Test case basic list for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    test_instance.subject_ids = ["a", "b", "c"]
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    tests_io("Succeeded testing basic list assignment.")
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]
    tests_io("Succeeded testing restoration of basic list assignment.")
    # We are tempering with the cls so need to make sure nothing is permanent
    del test_instance
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == []
    assert test_instance._progress["subject_ids"] == []
    tests_io("Succeeded testing list non permanency on database deletion.")


def test_list_extend():
    tests_io("Test case extend list for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    test_instance.subject_ids.extend(["a", "b", "c"])
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]
    tests_io("Succeeded testing extend list assignment.")

    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]
    tests_io("Succeeded testing restoration of extend list assignment.")

    test_instance.subject_ids.extend(["d", "e", "f"])
    assert test_instance.subject_ids == ["a", "b", "c", "d", "e", "f"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c", "d", "e", "f"]
    tests_io("Succeeded testing extend list assignment.")

    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c", "d", "e", "f"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c", "d", "e", "f"]
    tests_io("Succeeded testing restoration of extend list assignment.")


def test_list_pop():
    tests_io("Test case pop list for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    # Assign and make sure
    test_instance.subject_ids = ["a", "b", "c"]
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Now pop
    popper = test_instance.subject_ids.pop()
    assert popper == "c"
    assert test_instance.subject_ids == ["a", "b"]
    assert test_instance._progress["subject_ids"] == ["a", "b"]
    tests_io("Succeeded testing pop list assignment.")
    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b"]
    assert test_instance._progress["subject_ids"] == ["a", "b"]
    tests_io("Succeeded testing restoration of pop list assignment.")


def test_list_remove():
    tests_io("Test case remove list for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    # Assign and make sure
    test_instance.subject_ids = ["a", "b", "c"]
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Now remove
    test_instance.subject_ids.remove("b")
    assert test_instance.subject_ids == ["a", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "c"]
    tests_io("Succeeded testing remove list assignment.")

    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "c"]
    tests_io("Succeeded testing restoration of remove list assignment.")


def test_list_append():
    tests_io("Test case append list for storable decorator.", level=0)
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))

    # Assign and make sure
    test_instance.subject_ids = ["a", "b", "c"]
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c"]

    # Now append
    test_instance.subject_ids.append("d")
    assert test_instance.subject_ids == ["a", "b", "c", "d"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c", "d"]
    tests_io("Succeeded testing append list assignment.")

    # Restore to see if permament
    del test_instance
    test_instance = CountTestClass(Path(TEMP_DIR, "progress"))
    assert test_instance.subject_ids == ["a", "b", "c", "d"]
    assert test_instance._progress["subject_ids"] == ["a", "b", "c", "d"]
    tests_io("Succeeded testing restoration of append list assignment.")


def check_dtypes(instance):
    assert isinstance(instance.num_samples, int)
    assert isinstance(instance.time_elapsed, float)
    assert isinstance(instance.finished, bool)
    assert isinstance(instance.subjects, dict)
    assert isinstance(instance.names, dict)


if __name__ == "__main__":
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_list_basic()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_total_count()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_list_extend()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_list_append()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_list_pop()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_list_remove()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    test_total_count()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    TEMP_DIR.mkdir(exist_ok=True, parents=True)
    test_storable_basics()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    TEMP_DIR.mkdir(exist_ok=True, parents=True)
    test_dictionary_iadd()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))
    TEMP_DIR.mkdir(exist_ok=True, parents=True)
    test_dictionary_update()
    if TEMP_DIR.is_dir():
        shutil.rmtree(str(TEMP_DIR))

    tests_io("All tests passed")
