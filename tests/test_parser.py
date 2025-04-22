import os
import pytest

from pyparsing import ParseException
from catalog import Catalog, UnknownTableError, UnknownColumnError, CatalogError, IndexError_
from parser import SQLParser
from parser.validator import QueryValidator

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
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("SELECT id, name FROM users")
    validator.validate(result)
    # should parse without error and return a result structure
    assert result
    assert [col.column for col in result.columns] == ["id", "name"]


def test_parse_select_unknown_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    parsed = parser.parse("SELECT id FROM ghost")
    with pytest.raises(ParseException):
        validator.validate(parsed)


def test_parse_select_unknown_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    parsed = parser.parse("SELECT email FROM users")
    with pytest.raises(ParseException):
        validator.validate(parsed)


def test_parse_type_mismatch_in_where(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser()
    result = parser.parse("SELECT id FROM users WHERE id = 'abc'")
    # Type checking is not done at parse time anymore
    assert result


def test_parse_qualified_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("SELECT users.id FROM users")
    validator.validate(result)
    assert result
    assert result.columns[0].table[0] == "users"  # access the first element
    assert result.columns[0].column == "id"

def test_parse_logical_ops(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("SELECT id, name FROM users WHERE id = 1 AND name = 'Alice'")
    validator.validate(result)
    assert result

def test_parse_aggregation(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STRING"), ("age", "INT")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("SELECT COUNT(*) FROM users")
    validator.validate(result)
    assert result

# DDL Tests

def test_create_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("CREATE TABLE students (id INT, name STR, gpa INT)")
    validator.validate(result)
    
    # Execute the create table operation to test subsequent operations
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR"), ("gpa", "INT")], primary_key="id"
    )
    
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
    validator.validate(query_result)
    assert query_result


def test_create_table_duplicate(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create the table first time
    result = parser.parse("CREATE TABLE students (id INT, name STR)")
    validator.validate(result)
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # creating same table again should fail during validation
    result = parser.parse("CREATE TABLE students (id INT, name STR)")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_drop_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create the table
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )

    # drop table
    result = parser.parse("DROP TABLE students")
    validator.validate(result)
    clean_catalog.drop_table("students")
    
    # table should no longer exist
    with pytest.raises(UnknownTableError):
        clean_catalog.get_schema("students")
    
    # querying dropped table should fail during validation
    result = parser.parse("SELECT * FROM students")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_drop_nonexistent_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("DROP TABLE nonexistent")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_create_index(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table first
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR"), ("gpa", "INT")], primary_key="id"
    )
    
    # create index on column
    result = parser.parse("CREATE INDEX students name")
    validator.validate(result)
    clean_catalog.create_index("students", "name")
    
    # check if index was created
    schema = clean_catalog.get_schema("students")
    assert "name" in schema.indexes


def test_create_index_unknown_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("CREATE INDEX nonexistent name")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_create_index_unknown_column(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table first
    result = parser.parse("CREATE TABLE students (id INT, name STR)")
    validator.validate(result)
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # try to create index on nonexistent column
    result = parser.parse("CREATE INDEX students gpa")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_create_duplicate_index(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table first
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # create index
    result = parser.parse("CREATE INDEX students name")
    validator.validate(result)
    clean_catalog.create_index("students", "name")
    
    # creating same index again should fail during validation
    result = parser.parse("CREATE INDEX students name")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_drop_index(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table and index first
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    clean_catalog.create_index("students", "name")
    
    # drop the index
    result = parser.parse("DROP INDEX students name")
    validator.validate(result)
    clean_catalog.drop_index("students", "name")
    
    # index should no longer exist
    schema = clean_catalog.get_schema("students")
    assert "name" not in schema.indexes


def test_drop_nonexistent_index(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table but no index
    clean_catalog.create_table(
        "students", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    result = parser.parse("DROP INDEX students name")
    with pytest.raises(ParseException):
        validator.validate(result)


def test_integration_ddl_dml(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # create table
    result = parser.parse("CREATE TABLE employees (id INT, name STR, salary INT)")
    validator.validate(result)
    clean_catalog.create_table(
        "employees", [("id", "INT"), ("name", "STR"), ("salary", "INT")], primary_key="id"
    )
    
    # create index
    # Primary key index creation test removed as it's automatically indexed
    result = parser.parse("CREATE INDEX employees name")
    validator.validate(result)
    clean_catalog.create_index("employees", "name")
    
    # test SELECT query
    select_result = parser.parse("SELECT id, name FROM employees WHERE id = 1")
    validator.validate(select_result)
    assert select_result
    
    # drop an index
    result = parser.parse("DROP INDEX employees name")
    validator.validate(result)
    clean_catalog.drop_index("employees", "name")
    schema = clean_catalog.get_schema("employees")
    assert "name" not in schema.indexes
    assert "id" in schema.indexes
    
    # drop table
    result = parser.parse("DROP TABLE employees")
    validator.validate(result)
    clean_catalog.drop_table("employees")
    with pytest.raises(UnknownTableError):
        clean_catalog.get_schema("employees")


# DML Tests: INSERT, UPDATE, DELETE

def test_parse_insert_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    # should parse without error
    result = parser.parse("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    validator.validate(result)
    assert result

def test_parse_insert_column_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    # too many columns
    result = parser.parse("INSERT INTO users (id, name) VALUES (1, 'Alice', 'Extra')")
    with pytest.raises(ParseException):
        validator.validate(result)

def test_parse_insert_type_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    # Type checking happens at execution time, not at parse/validate time
    result = parser.parse("INSERT INTO users (id, name) VALUES ('oops', 'Alice')")
    assert result

def test_parse_update_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    # should parse without error
    result = parser.parse("UPDATE users SET name = 'Bob' WHERE id = 1")
    validator.validate(result)
    assert result

def test_parse_update_unknown_column(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("UPDATE users SET email = 'bob@example.com' WHERE id = 1")
    with pytest.raises(ParseException):
        validator.validate(result)

def test_parse_update_type_mismatch(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    # Type checking happens at execution time, not at parse/validate time
    result = parser.parse("UPDATE users SET name = 123 WHERE id = 1")
    assert result

def test_parse_delete_valid(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    # should parse without error
    result = parser.parse("DELETE FROM users WHERE id = 1")
    validator.validate(result)
    assert result

def test_parse_delete_unknown_table(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("DELETE FROM ghosts WHERE id = 1")
    with pytest.raises(ParseException):
        validator.validate(result)

def test_parse_delete_type_mismatch_in_where(clean_catalog):
    clean_catalog.create_table(
        "users", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    parser = SQLParser()
    # Type checking happens at execution time, not at parse/validate time
    result = parser.parse("DELETE FROM users WHERE id = 'abc'")
    assert result

def test_parse_syntax_error(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    with pytest.raises(ParseException):
        q = parser.parse("SELECT FROM users")  # Missing columns
        validator.validate(q)

def test_create_table_parse_with_primary_key(clean_catalog):
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    result = parser.parse("CREATE TABLE students (id INT, name STR, PRIMARY KEY (id))")
    validator.validate(result)
    assert result
    