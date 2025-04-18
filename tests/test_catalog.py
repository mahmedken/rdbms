import os
import pytest

from catalog import Catalog, DuplicateTableError, UnknownTableError, IndexError_  # noqa: F401


@pytest.fixture(autouse=True)
def clean_catalog(tmp_path, monkeypatch):
    """each test get a new catalog in a tmp dir"""
    cat_path = tmp_path / "cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    catalog = Catalog()
    yield catalog 
    # delete the catalog file after each test
    catalog.reset()


def test_create_and_list():
    c = Catalog()
    c.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    assert c.list_tables() == ["users"]
    schema = c.get_schema("users")
    assert schema.primary_key == "id"
    assert schema.indexes == ["id"]


def test_duplicate_table():
    c = Catalog()
    c.create_table("t1", [("id", "INT")])
    with pytest.raises(DuplicateTableError):
        c.create_table("t1", [("id", "INT")])


def test_unknown_table():
    c = Catalog()
    with pytest.raises(UnknownTableError):
        c.get_schema("ghost")


def test_index_management():
    c = Catalog()
    c.create_table("items", [("sku", "INT"), ("desc", "STR")])
    c.create_index("items", "sku")
    assert "sku" in c.get_schema("items").indexes
    c.drop_index("items", "sku")
    assert c.get_schema("items").indexes == []
    with pytest.raises(IndexError_):
        c.drop_index("items", "sku")