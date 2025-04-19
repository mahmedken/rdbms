import os
import pytest

from pyparsing import ParseException
from catalog import Catalog, UnknownTableError, UnknownColumnError, CatalogError
from parser import SQLParser

@pytest.fixture(autouse=True)
def clean_catalog(tmp_path, monkeypatch):
    """each test get a new catalog in a tmp dir"""
    cat_path = tmp_path / "cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    catalog = Catalog()
    yield catalog
    catalog.reset()


def test_parse_simple_select(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    result = parser.parse("SELECT id, name FROM users")
    # should parse without error and return a result structure
    assert result
    assert [col.column for col in result.columns] == ["id", "name"]


def test_parse_select_unknown_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    with pytest.raises(ParseException): 
        parser.parse("SELECT id FROM ghost")



def test_parse_select_unknown_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    with pytest.raises(Exception):  
        parser.parse("SELECT email FROM users")


def test_parse_type_mismatch_in_where(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # WHERE id = 'abc' should fail (id is INT, 'abc' is STR)
    with pytest.raises(Exception):  # replace with type error !
        parser.parse("SELECT id FROM users WHERE id = 'abc'")


def test_parse_qualified_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    result = parser.parse("SELECT users.id FROM users")
    assert result
    assert result.columns[0].table[0] == "users"  # access the first element
    assert result.columns[0].column == "id"
