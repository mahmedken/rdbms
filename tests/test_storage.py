import os
import tempfile
from pathlib import Path

import pytest

from catalog import Catalog
from storage.heap_file import HeapFile


@pytest.fixture()
def setup_env(tmp_path, monkeypatch):
    # fresh catalog file per test
    cat_path = tmp_path / "cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    data_dir = tmp_path / "data"
    catalog = Catalog()
    yield catalog, data_dir
    catalog.reset() # clean up after test


def test_insert_and_scan(setup_env):
    catalog, data_dir = setup_env
    catalog.create_table("people", [("id", "INT"), ("name", "STR")], primary_key="id")
    heap = HeapFile(catalog, data_dir, "people")
    heap.insert(1, "Alice")
    heap.insert(2, "Bob")
    rows = list(heap.scan())
    assert rows == [(1, "Alice"), (2, "Bob")]


def test_pk_uniqueness(setup_env):
    catalog, data_dir = setup_env
    catalog.create_table("ttt", [("id", "INT"), ("val", "STR")], primary_key="id")
    heap = HeapFile(catalog, data_dir, "ttt")
    heap.insert(1, "x")
    with pytest.raises(ValueError):
        heap.insert(1, "duplicate")


def test_get_by_pk(setup_env):
    catalog, data_dir = setup_env
    catalog.create_table("itz", [("sku", "INT"), ("desc", "STR")], primary_key="sku")
    heap = HeapFile(catalog, data_dir, "itz")
    heap.insert(10, "foo")
    heap.insert(20, "bar")
    assert heap.get_by_pk(20) == (20, "bar")
    assert heap.get_by_pk(99) is None