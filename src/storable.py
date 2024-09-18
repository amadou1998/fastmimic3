"""Provides a storable dataclass with some custom dictionary operations for trackers.
Attempted thread safety but didn't work out too well. Use an external lock. 
Designed to work multiple processes.
"""
import shelve
import multiprocess as mp
from copy import deepcopy
from pathlib import Path
from typing import Any


class SimpleProperty(object):
    """
    A simple descriptor class for storing and retrieving property values.
    """

    def __init__(self, name: str, default: Any = 0):
        self._name = name
        self._default = default

    def __get__(self, instance, owner) -> Any:

        return instance._progress.get(self._name, self._default)

    def __set__(self, instance, value: Any):
        instance._progress[self._name] = value
        instance._write({self._name: value})


class FloatPropert(SimpleProperty):
    """
    A descriptor class for storing and retrieving float property values.
    """

    def __init__(self, name: str, default: float):
        super().__init__(name, default)

    def __get__(self, instance, owner) -> float:
        return super().__get__(instance, owner)

    def __set__(self, instance, value: float):
        super().__set__(instance, value)


class BoolProperty(SimpleProperty):
    """
    A descriptor class for storing and retrieving bool property values.
    """

    def __init__(self, name: str, default: bool):
        super().__init__(name, default)

    def __get__(self, instance, owner) -> bool:
        return super().__get__(instance, owner)

    def __set__(self, instance, value: bool):
        super().__set__(instance, value)


class IntProperty(SimpleProperty):
    """
    A descriptor class for storing and retrieving int property values.
    """

    def __init__(self, name: str, default: int):
        super().__init__(name, default)

    def __get__(self, instance, owner) -> int:
        return super().__get__(instance, owner)

    def __set__(self, instance, value: int):
        super().__set__(instance, value)


class ProxyDictionary(dict):
    """
    A dictionary subclass that allows for callback on modification.
    """

    def __init__(self,
                 name: str,
                 default: dict = None,
                 store_total: bool = False,
                 write_callback=None,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._name = name
        self._store_total = store_total
        self._on_modified = write_callback
        if store_total:
            if "total" not in default:
                # If the dict is created from scratch, total is created in the first update
                # After that it is assumed that total is correctly updated
                self._is_initial = False
                self["total"] = 0
            else:
                self._is_initial = True

            if not self._is_initial:
                self._on_modified(self._name, self, *args, **kwargs)
        self.update(default)
        self._is_initial = False
        return

    def _update_total(self, key, value):
        if self._store_total:
            if isinstance(value, dict):
                if not self._is_initial:
                    if key not in self or isinstance(self[key], (int, float)):
                        if len(value):
                            orig_value = self.get(key, 0)
                            super().__setitem__(key, dict())
                            self[key]["total"] = sum(
                                [stay_data for stay, stay_data in value.items() if stay != "total"])
                            self["total"] += self[key]["total"] - orig_value
                    elif len(value):
                        length = self[key].get("total", 0)
                        new_length = sum([
                            stay_data for stay, stay_data in self[key].items() if stay != "total"
                        ]) + length
                        self[key]["total"] = new_length
                        if not self._is_initial:
                            self["total"] += new_length - length

            elif isinstance(value, (int, float)):
                if not (key == "total" or self._is_initial):
                    orig_value = self.get(key, 0)
                    self["total"] += value - orig_value

    def __iadd__(self, other, *args, **kwargs):
        if set(other.keys()) - set(self.keys()):
            raise ValueError(
                f"Keys in the dictionary must match to __iadd__! stored_keys: {list(self.keys())}; added_keys: {list(other.keys())}"
            )
        for key, value in other.items():
            self._update_total(key, value)
        for key in other.keys():
            self[key] += other[key]
        if self._on_modified:
            self._on_modified(self._name, self, *args, **kwargs)
        return self

    def __setitem__(self, key, value):
        self._update_total(key, value)
        if self._store_total and isinstance(value, dict) and key in self:
            self[key].update(value)
        else:
            super().__setitem__(key, value)
        if self._on_modified:
            self._on_modified(self._name, self)
        return

    def __delitem__(self, key):
        super().__delitem__(key)
        if self._on_modified:
            self._on_modified(self._name, self)

    def update(self, other, *args, **kwargs):
        """
        Update the dictionary with the values from another dictionary.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        for key, value in other.items():
            if key in self and isinstance(self[key], dict) and isinstance(value, dict):
                self._update_total(key, value)
                self._recursive_update(self[key], value)
            else:
                self[key] = value

        if self._on_modified:
            self._on_modified(self._name, self)
        return

    def _recursive_update(self, dictionary, update):
        """
        Recursively update a dictionary with the values from another dictionary.

        Args:
            d (dict): The dictionary to update.
            u (dict): The dictionary with the new values.
        """
        for key, value in update.items():
            if isinstance(dictionary.get(key), dict) and isinstance(update[key], dict):
                self._update_total(key, value)
                self._recursive_update(dictionary[key], update[key])
            else:
                dictionary[key] = update[key]


class ProxyList(list):
    """
    A list subclass that allows for callback on modification.
    """

    def __init__(self, name, initial=None, write_callback=None, *args, **kwargs):
        self._on_modified = write_callback
        super().__init__(*args, **kwargs)
        self._name = name
        if initial is None:
            initial = []
        self.extend(initial)

    def append(self, item):
        super().append(item)
        if self._on_modified:
            self._on_modified(self._name, self)

    def extend(self, items):
        super().extend(items)
        if self._on_modified:
            self._on_modified(self._name, self)

    def insert(self, index, item):
        super().insert(index, item)
        if self._on_modified:
            self._on_modified(self._name, self)

    def remove(self, item):
        super().remove(item)
        if self._on_modified:
            self._on_modified(self._name, self)

    def pop(self, index=-1):
        item = super().pop(index)
        if self._on_modified:
            self._on_modified(self._name, self)
        return item

    def clear(self):
        super().clear()
        if self._on_modified:
            self._on_modified(self._name, self)

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        if self._on_modified:
            self._on_modified(self._name, self)

    def __delitem__(self, index):
        super().__delitem__(index)
        if self._on_modified:
            self._on_modified(self._name, self)


class ListProperty:
    """
    A descriptor class for storing and retrieving list property values.
    """

    def __init__(self, name: str, default=None, write_callback=None):
        self._name = name
        self._write_callback = write_callback
        self._default = default

    def __get__(self, instance, owner):
        if instance is not None:
            if self._name not in instance.__dict__:
                instance._progress[self._name] = instance._read(self._name)
                return ProxyList(name=self._name,
                                 initial=instance._progress.get(self._name, self._default),
                                 write_callback=lambda n, x: self.__set__(instance, x))
        else:
            return deepcopy(owner._originals.get(self._name, self._default))

    def __set__(self, instance, value):
        if isinstance(value, ProxyList):
            value = list(value)
        # instance.__dict__[self._name] = value
        # if self._write_callback:
        #     self._write_callback(self._name, value)
        instance._progress[self._name] = value
        instance._write({self._name: value})


class DictionaryProperty(object):
    """
    A descriptor class for storing and retrieving dictionary property values.
    """

    def __init__(self, name: str, default: dict = {}, store_total=False, write_callback=None):
        self._name = name
        self._store_total = store_total
        self._write_callback = (write_callback if store_total else None)
        self._default = ProxyDictionary(self._name,
                                        default,
                                        write_callback=write_callback,
                                        store_total=self._store_total)

    def __get__(self, instance, owner) -> dict:
        if instance is not None:
            instance._progress[self._name] = instance._read(self._name)
            return ProxyDictionary(self._name,
                                   instance._progress.get(self._name, self._default),
                                   write_callback=lambda n, x: self.__set__(instance, x),
                                   store_total=self._store_total)
        elif owner is not None:
            return deepcopy(owner._originals.get(self._name, self._default))

    def __set__(self, instance, value: dict):
        if isinstance(value, ProxyDictionary):
            value = dict(value)
        elif self._store_total:
            value = dict(
                ProxyDictionary(self._name,
                                value,
                                store_total=True,
                                write_callback=self._write_callback))
        instance._progress[self._name] = value
        instance._write({self._name: value})


import sqlitedict


def storable(cls):
    """
    A class decorator that adds persistence functionality to a class.

    Args:
        cls: The class to decorate.

    Returns:
        The decorated class.
    """
    # When you think about it this is highly illegal but the only way of keeping them cls attributes unchanged between instantiations.
    # Find a better way if you can, you are the real hero.
    originals = {
        name: deepcopy(attr)
        for name, attr in vars(cls).items()
        if not name.startswith("_") and isinstance(attr, (int, float, bool, dict, list, type(None)))
    }
    setattr(cls, '_originals', originals)
    original_init = cls.__init__

    def __init__(self, *args, **kwargs):
        """
        Initialize the storable class.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        self._lock = mp.Lock()
        self._progress = {}
        for name, original_value in cls._originals.items():
            setattr(cls, name, deepcopy(original_value))

        if "storage_path" in kwargs:
            self._path = Path(kwargs.pop('storage_path'))
        elif args:
            self._path = Path(args[0])
            args = tuple(args[1:])
        else:
            raise ValueError(
                "No storage path provided to storable. Either provide as first positional argument or with the storage_path keyword argument."
            )

        self._path.parent.mkdir(exist_ok=True, parents=True)

        self._save_frequency = kwargs.pop('save_frequency', 1)
        self._access_count = 0

        # Load or initialize progress
        if Path(self._path.parent, f"{self._path.name}").is_file():
            self._progress = self._read()
            self._wrap_attributes()
        else:
            self._wrap_attributes()
            self._write(self._progress)

        original_init(self, *args, **kwargs)

    def _write(self, items: dict):
        """
        Write the current state of the progress to the file.

        Args:
            items (dict): The dictionary containing the progress items.
        """
        self._access_count += 1

        # Open the SQLiteDict with autocommit=False for better control
        with sqlitedict.SqliteDict(str(self._path), autocommit=False) as db:
            for key, value in items.items():
                # Make sure no Property types are written back
                if isinstance(value, ProxyDictionary):
                    db[key] = dict(value)
                elif isinstance(value, ProxyList):
                    db[key] = list(value)
                else:
                    db[key] = value
            db.commit()  # Commit the changes

    def _read(self, key=None):
        """
        Read the progress from the file.

        Returns:
            dict: The progress dictionary.
        """
        with sqlitedict.SqliteDict(str(self._path), autocommit=True) as db:

            def _read_value(key):
                value = db[key]
                default_value = cls._originals.get(key, None)
                # These types are miscast by shelve/sqlitedict
                if isinstance(default_value, bool):
                    return bool(value)
                elif isinstance(default_value, int):
                    return int(value)
                else:
                    return value

            if key is None:
                ret = dict()
                for key in db.keys():
                    ret[key] = _read_value(key)
            else:
                ret = _read_value(key)

        return ret

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._wrap_attributes()

    cls.__setstate__ = __setstate__
    cls.__init__ = __init__
    cls._write = _write
    cls._read = _read

    # Attribute wrapping logic
    def _wrap_attributes(self):
        """
        Wrap the attributes of the class with the appropriate descriptors.
        """

        for name, attr in vars(cls).items():
            if (isinstance(attr, (int, float, bool, dict, list)) or
                    attr is None) and not name.startswith("_"):
                attr = self._progress.get(name, attr)

                def _write_callback(name, value):
                    # Read before you _write like github
                    self._progress[name] = value
                    self._write({name: value})

                if isinstance(attr, dict):
                    # Store total is a mess but necessary for preprocessing trackers
                    store_total = getattr(cls, "_store_total", False)
                    setattr(
                        cls, name,
                        DictionaryProperty(name, attr, store_total, write_callback=_write_callback))
                elif isinstance(attr, list):
                    setattr(cls, name, ListProperty(name, attr, write_callback=_write_callback))
                elif isinstance(attr, bool):
                    setattr(cls, name, BoolProperty(name, attr))
                elif isinstance(attr, float):
                    setattr(cls, name, FloatPropert(name, attr))
                else:
                    setattr(cls, name, IntProperty(name, attr))
                self._progress[name] = attr

    cls._wrap_attributes = _wrap_attributes

    return cls
