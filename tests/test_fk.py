import os
import pytest

from pyparsing import ParseException
from catalog import Catalog, UnknownTableError, CatalogError
from parser import SQLParser
from parser.validator import QueryValidator
from engine.executor import Executor

@pytest.fixture(autouse=True)
def clean_catalog(tmp_path, monkeypatch):
    """each test get a new catalog in a tmp dir"""
    cat_path = tmp_path / "cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    catalog = Catalog()
    yield catalog
    catalog.reset()

@pytest.fixture
def parser():
    return SQLParser()

@pytest.fixture
def validator(clean_catalog):
    return QueryValidator(clean_catalog)

@pytest.fixture
def executor(clean_catalog, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return Executor(clean_catalog, str(data_dir))

def test_create_table_with_foreign_key(clean_catalog, parser, validator):
    # First create the parent table
    create_parent = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(create_parent)
    clean_catalog.create_table(
        "departments", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # Then create a child table with foreign key reference
    create_child = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, salary INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(create_child)
    clean_catalog.create_table(
        "employees", [("id", "INT"), ("name", "STR"), ("dept_id", "INT"), ("salary", "INT")], primary_key="id", foreign_keys={"dept_id": ("departments", "id")}
    )
    
    # Verify the schema has the foreign key information
    schema = clean_catalog.get_schema("employees")
    assert schema.foreign_keys is not None
    assert "dept_id" in schema.foreign_keys
    assert schema.foreign_keys["dept_id"] == ("departments", "id")

def test_create_table_with_multiple_foreign_keys(clean_catalog, parser, validator):
    # Create parent tables
    clean_catalog.create_table(
        "departments", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    clean_catalog.create_table(
        "projects", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # Create child table with multiple foreign keys
    create_child = parser.parse(
        "CREATE TABLE assignments (id INT, emp_id INT, dept_id INT, project_id INT, "
        "PRIMARY KEY(id), "
        "FOREIGN KEY(dept_id) REFERENCES departments(id), "
        "FOREIGN KEY(project_id) REFERENCES projects(id))"
    )
    validator.validate(create_child)
    clean_catalog.create_table(
        "assignments", [("id", "INT"), ("emp_id", "INT"), ("dept_id", "INT"), ("project_id", "INT")], primary_key="id", foreign_keys={"dept_id": ("departments", "id"), "project_id": ("projects", "id")}
    )
    
    # Verify the schema has both foreign key constraints
    schema = clean_catalog.get_schema("assignments")
    assert schema.foreign_keys is not None
    assert len(schema.foreign_keys) == 2
    assert schema.foreign_keys["dept_id"] == ("departments", "id")
    assert schema.foreign_keys["project_id"] == ("projects", "id")

def test_foreign_key_to_nonexistent_table(clean_catalog, parser, validator):
    # Try to create a table referencing a nonexistent parent table
    create_child = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    
    # Should fail validation
    with pytest.raises(ParseException, match="referenced table departments does not exist"):
        validator.validate(create_child)

def test_foreign_key_to_nonexistent_column(clean_catalog, parser, validator):
    # Create parent table
    clean_catalog.create_table(
        "departments", [("id", "INT"), ("name", "STR")], primary_key="id"
    )
    
    # Try to reference a nonexistent column
    create_child = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_code INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_code) REFERENCES departments(code))"
    )
    
    # Should fail validation
    with pytest.raises(ParseException, match="referenced column code not found in departments"):
        validator.validate(create_child)

def test_foreign_key_to_non_indexed_column(clean_catalog, parser, validator):
    # Create parent table without explicitly making the referenced column a primary key
    clean_catalog.create_table(
        "departments", [("id", "INT"), ("code", "STR"), ("name", "STR")], primary_key="id"
    )
    
    # Try to reference a non-indexed column
    create_child = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_code STR, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_code) REFERENCES departments(code))"
    )
    
    # Should fail validation because the referenced column isn't indexed
    with pytest.raises(ParseException, match="referenced column code is not indexed in departments"):
        validator.validate(create_child)
        
    # Now let's index the column and try again
    clean_catalog.create_index("departments", "code")
    validator.validate(create_child)  # Should pass now

def test_insert_with_valid_foreign_key(clean_catalog, parser, validator, executor):
    # Set up parent and child tables
    parent_query = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(parent_query)
    executor.run(parent_query)
    
    child_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(child_query)
    executor.run(child_query)
    
    # Insert into parent table
    insert_parent = parser.parse("INSERT INTO departments (id, name) VALUES (1, 'Engineering')")
    validator.validate(insert_parent)
    executor.run(insert_parent)
    
    # Insert into child table with valid foreign key
    insert_child = parser.parse("INSERT INTO employees (id, name, dept_id) VALUES (101, 'Alice', 1)")
    validator.validate(insert_child)
    result, _ = executor.run(insert_child)
    
    # Verify successful insertion
    assert result[0]["operation"] == "INSERT"
    assert result[0]["rows_affected"] == 1

def test_insert_with_invalid_foreign_key(clean_catalog, parser, validator, executor):
    # Set up parent and child tables
    parent_query = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(parent_query)
    executor.run(parent_query)
    
    child_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(child_query)
    executor.run(child_query)
    
    # Insert into parent table
    insert_parent = parser.parse("INSERT INTO departments (id, name) VALUES (1, 'Engineering')")
    validator.validate(insert_parent)
    executor.run(insert_parent)
    
    # Try to insert with invalid foreign key (dept_id=999 doesn't exist)
    insert_child = parser.parse("INSERT INTO employees (id, name, dept_id) VALUES (101, 'Alice', 999)")
    validator.validate(insert_child)
    
    # Should fail with constraint violation
    with pytest.raises(ValueError, match="Foreign key constraint violation"):
        executor.run(insert_child)

def test_update_with_invalid_foreign_key(clean_catalog, parser, validator, executor):
    # Set up parent and child tables
    parent_query = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(parent_query)
    executor.run(parent_query)
    
    child_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(child_query)
    executor.run(child_query)
    
    # Insert valid data
    executor.run(parser.parse("INSERT INTO departments (id, name) VALUES (1, 'Engineering')"))
    executor.run(parser.parse("INSERT INTO employees (id, name, dept_id) VALUES (101, 'Alice', 1)"))
    
    # Try to update with invalid foreign key
    update_query = parser.parse("UPDATE employees SET dept_id = 999 WHERE id = 101")
    validator.validate(update_query)
    
    # Should fail with constraint violation
    with pytest.raises(ValueError, match="Foreign key constraint violation"):
        executor.run(update_query)

def test_delete_referenced_row(clean_catalog, parser, validator, executor):
    # Set up parent and child tables
    parent_query = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(parent_query)
    executor.run(parent_query)
    
    child_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(child_query)
    executor.run(child_query)
    
    # Insert valid data
    executor.run(parser.parse("INSERT INTO departments (id, name) VALUES (1, 'Engineering')"))
    executor.run(parser.parse("INSERT INTO employees (id, name, dept_id) VALUES (101, 'Alice', 1)"))
    
    # Try to delete the referenced department
    delete_query = parser.parse("DELETE FROM departments WHERE id = 1")
    validator.validate(delete_query)
    
    # Should fail with constraint violation
    with pytest.raises(ValueError, match="Foreign key constraint violation"):
        executor.run(delete_query)
        
    # Delete employee first, then department should succeed
    executor.run(parser.parse("DELETE FROM employees WHERE id = 101"))
    result, _ = executor.run(delete_query)
    assert result[0]["operation"] == "DELETE"
    assert result[0]["rows_affected"] == 1

def test_drop_referenced_table(clean_catalog, parser, validator, executor):
    # Set up parent and child tables
    parent_query = parser.parse("CREATE TABLE departments (id INT, name STR, PRIMARY KEY(id))")
    validator.validate(parent_query)
    executor.run(parent_query)
    
    child_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(child_query)
    executor.run(child_query)

    
    # Try to drop the parent table
    drop_query = parser.parse("DROP TABLE departments")
    validator.validate(drop_query)
    
    # Should fail because table is referenced by FK
    #with pytest.raises(CatalogError, match="Table departments referenced by FK; cannot drop"):
    result, _ = executor.run(drop_query)
    print(result)
    assert result[0]["message"] == "Error: Table departments referenced by FK; cannot drop"