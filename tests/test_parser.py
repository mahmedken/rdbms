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

def test_parse_logical_ops(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    result = parser.parse("SELECT id, name FROM users WHERE id = 1 AND name = 'Alice'")
    assert result

def test_parse_aggregation(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING"), ("age", "INT")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    result = parser.parse("SELECT COUNT(*) FROM users")

# DDL Tests

def test_create_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    result = parser.parse("CREATE TABLE students (id INT, name STR, gpa INT)")
    
    # check if the table was added to the catalog
    schema = clean_catalog.get_schema("students")
    assert schema is not None
    
    # check column names
    col_names = schema.col_names()
    assert "id" in col_names
    assert "name" in col_names
    assert "gpa" in col_names
    
    # test that we can now query this table
    query_result = parser.parse("SELECT id, name, gpa FROM students")
    assert query_result


def test_create_table_duplicate(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create the table first time
    parser.parse("CREATE TABLE students (id INT, name STR)")
    
    # creating same table again should fail
    with pytest.raises(ParseException):
        parser.parse("CREATE TABLE students (id INT, name STR)")


def test_drop_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create and then drop the table
    parser.parse("CREATE TABLE students (id INT, name STR)")
    result = parser.parse("DROP TABLE students")
    
    # table should no longer exist
    with pytest.raises(UnknownTableError):
        clean_catalog.get_schema("students")
    
    # querying dropped table should fail
    with pytest.raises(ParseException):
        parser.parse("SELECT * FROM students")


def test_drop_nonexistent_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    with pytest.raises(ParseException):
        parser.parse("DROP TABLE nonexistent")


def test_create_index(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create table first
    parser.parse("CREATE TABLE students (id INT, name STR, gpa INT)")
    
    # create index on column
    result = parser.parse("CREATE INDEX students name")
    
    # check if index was created
    schema = clean_catalog.get_schema("students")
    assert "name" in schema.indexes


def test_create_index_unknown_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    with pytest.raises(ParseException):
        parser.parse("CREATE INDEX nonexistent name")


def test_create_index_unknown_column(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create table first
    parser.parse("CREATE TABLE students (id INT, name STR)")
    
    # try to create index on nonexistent column
    with pytest.raises(ParseException):
        parser.parse("CREATE INDEX students gpa")


def test_create_duplicate_index(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create table first
    parser.parse("CREATE TABLE students (id INT, name STR)")
    
    # create index
    parser.parse("CREATE INDEX students name")
    
    # creating same index again should fail
    with pytest.raises(ParseException):
        parser.parse("CREATE INDEX students name")


def test_drop_index(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create table and index first
    parser.parse("CREATE TABLE students (id INT, name STR)")
    parser.parse("CREATE INDEX students name")
    
    # drop the index
    result = parser.parse("DROP INDEX students name")
    
    # index should no longer exist
    schema = clean_catalog.get_schema("students")
    assert "name" not in schema.indexes


def test_drop_nonexistent_index(clean_catalog):
    parser = SQLParser(clean_catalog)
    # create table but no index
    parser.parse("CREATE TABLE students (id INT, name STR)")
    
    with pytest.raises(ParseException):
        parser.parse("DROP INDEX students name")


def test_integration_ddl_dml(clean_catalog):
    parser = SQLParser(clean_catalog)
    
    # create table
    parser.parse("CREATE TABLE employees (id INT, name STR, salary INT)")
    
    # create indexes
    parser.parse("CREATE INDEX employees id")
    parser.parse("CREATE INDEX employees name")
    
    # test SELECT query
    select_result = parser.parse("SELECT id, name FROM employees WHERE id = 1")
    assert select_result
    
    # drop an index
    parser.parse("DROP INDEX employees name")
    schema = clean_catalog.get_schema("employees")
    assert "name" not in schema.indexes
    assert "id" in schema.indexes
    
    # drop table
    parser.parse("DROP TABLE employees")
    with pytest.raises(UnknownTableError):
        clean_catalog.get_schema("employees")




# DML Tests: INSERT, UPDATE, DELETE

def test_parse_insert_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # should parse without error
    result = parser.parse("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    assert result

def test_parse_insert_column_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # too many columns
    with pytest.raises(Exception):
        parser.parse("INSERT INTO users (id, name) VALUES (1, 'Alice', 'Extra')")

def test_parse_insert_type_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # id expects INT, but gets STR
    with pytest.raises(Exception):
        parser.parse("INSERT INTO users (id, name) VALUES ('oops', 'Alice')")

def test_parse_update_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # should parse without error
    result = parser.parse("UPDATE users SET name = 'Bob' WHERE id = 1")
    assert result

def test_parse_update_unknown_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    with pytest.raises(Exception):
        parser.parse("UPDATE users SET email = 'bob@example.com' WHERE id = 1")

def test_parse_update_type_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # name expects STR, but gets INT
    with pytest.raises(Exception):
        parser.parse("UPDATE users SET name = 123 WHERE id = 1")

def test_parse_delete_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # should parse without error
    result = parser.parse("DELETE FROM users WHERE id = 1")
    assert result

def test_parse_delete_unknown_table(clean_catalog):
    parser = SQLParser(clean_catalog)
    with pytest.raises(ParseException):
        parser.parse("DELETE FROM ghosts WHERE id = 1")

def test_parse_delete_type_mismatch_in_where(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser(clean_catalog)
    # id expects INT, gets STR
    with pytest.raises(Exception):
        parser.parse("DELETE FROM users WHERE id = 'abc'")