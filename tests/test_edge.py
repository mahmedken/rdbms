import pytest
from pathlib import Path

from pyparsing import ParseException
from catalog import Catalog, UnknownTableError, CatalogError
from parser import SQLParser
from parser.validator import QueryValidator
from engine.executor import Executor
from storage.heap_file import HeapFile

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
    data_dir = tmp_path / "tmp_data"
    data_dir.mkdir(exist_ok=True)
    return Executor(clean_catalog, str(data_dir))

@pytest.fixture
def setup_fk_tables(clean_catalog, parser, validator, executor):
    """Setup departments and employees tables with foreign key relationship"""
    # Create departments table
    dept_query = parser.parse("CREATE TABLE departments (id INT, name STR, location STR, PRIMARY KEY(id))")
    validator.validate(dept_query)
    executor.run(dept_query)
    
    # Create employees table with foreign key
    emp_query = parser.parse(
        "CREATE TABLE employees (id INT, name STR, salary INT, dept_id INT, "
        "PRIMARY KEY(id), FOREIGN KEY(dept_id) REFERENCES departments(id))"
    )
    validator.validate(emp_query)
    executor.run(emp_query)
    
    # Insert departments data
    dept_data = [
        "INSERT INTO departments (id, name, location) VALUES (1, 'Engineering', 'Building A')",
        "INSERT INTO departments (id, name, location) VALUES (2, 'Marketing', 'Building B')",
        "INSERT INTO departments (id, name, location) VALUES (3, 'HR', 'Building C')",
    ]
    
    for query_str in dept_data:
        q = parser.parse(query_str)
        validator.validate(q)
        executor.run(q)
    
    # Insert employees data
    emp_data = [
        "INSERT INTO employees (id, name, salary, dept_id) VALUES (101, 'Alice', 80000, 1)",
        "INSERT INTO employees (id, name, salary, dept_id) VALUES (102, 'Bob', 70000, 1)",
        "INSERT INTO employees (id, name, salary, dept_id) VALUES (103, 'Charlie', 75000, 2)",
        "INSERT INTO employees (id, name, salary, dept_id) VALUES (104, 'David', 85000, 2)",
        "INSERT INTO employees (id, name, salary, dept_id) VALUES (105, 'Eve', 90000, 3)",
    ]
    
    for query_str in emp_data:
        q = parser.parse(query_str)
        validator.validate(q)
        executor.run(q)
    
    return clean_catalog, parser, validator, executor

def test_fk_tables_created_successfully(setup_fk_tables):
    """Test that departments and employees tables with FK were created successfully"""
    catalog, parser, validator, executor = setup_fk_tables
    
    # Check departments schema
    dept_schema = catalog.get_schema("departments")
    assert dept_schema is not None
    assert dept_schema.primary_key == "id"
    assert len(dept_schema.columns) == 3
    
    # Check employees schema
    emp_schema = catalog.get_schema("employees")
    assert emp_schema is not None
    assert emp_schema.primary_key == "id"
    assert len(emp_schema.columns) == 4
    
    # Verify foreign key
    assert emp_schema.foreign_keys is not None
    assert "dept_id" in emp_schema.foreign_keys
    assert emp_schema.foreign_keys["dept_id"] == ("departments", "id")
    
    # Verify data was inserted
    q = parser.parse("SELECT COUNT(*) FROM departments")
    validator.validate(q)
    rows, _ = executor.run(q)
    assert rows[0]["COUNT(*)"] == 3
    
    q = parser.parse("SELECT COUNT(*) FROM employees")
    validator.validate(q)
    rows, _ = executor.run(q)
    assert rows[0]["COUNT(*)"] == 5

def test_simple_join_with_fk(setup_fk_tables):
    """Test a simple join between departments and employees using FK relationship"""
    _, parser, validator, executor = setup_fk_tables
    
    # Execute join query
    join_query = parser.parse(
        "SELECT e.name, d.name FROM employees AS e, departments AS d "
        "WHERE e.dept_id = d.id"
    )
    validator.validate(join_query)
    rows, _ = executor.run(join_query)
    print(rows)
    # Should return all 5 employees with their department names
    assert len(rows) == 5
    
    # Create a lookup to verify results
    emp_dept_map = {
        "Alice": "Engineering",
        "Bob": "Engineering",
        "Charlie": "Marketing",
        "David": "Marketing",
        "Eve": "HR"
    }
    
    # Verify each employee is matched with the correct department
    for row in rows:
        emp_name = row["e.name"]
        dept_name = row["d.name"]
        assert dept_name == emp_dept_map[emp_name]

def test_join_with_additional_filter(setup_fk_tables):
    """Test a join with additional filtering conditions"""
    _, parser, validator, executor = setup_fk_tables
    
    # Join employees and departments, but only for Engineering department
    join_query = parser.parse(
        "SELECT e.name, e.salary, d.name, d.location "
        "FROM employees AS e, departments AS d "
        "WHERE e.dept_id = d.id AND d.name = 'Engineering'"
    )
    validator.validate(join_query)
    rows, _ = executor.run(join_query)
    
    # Should return only Engineering employees (Alice and Bob)
    assert len(rows) == 2
    
    # Verify the engineers are returned
    names = [row["e.name"] for row in rows]
    assert "Alice" in names
    assert "Bob" in names
    
    # Verify department information is correct
    for row in rows:
        assert row["d.name"] == "Engineering"
        assert row["d.location"] == "Building A"

def test_join_with_aggregation(setup_fk_tables):
    """Test a join with aggregation to get department statistics"""
    _, parser, validator, executor = setup_fk_tables
    
    # Calculate average salary by department
    agg_query = parser.parse(
        "SELECT d.name, COUNT(*), AVG(e.salary) "
        "FROM employees AS e, departments AS d "
        "WHERE e.dept_id = d.id "
        "GROUP BY d.name"
    )
    validator.validate(agg_query)
    rows, _ = executor.run(agg_query)
    
    # Should return 3 departments with their stats
    assert len(rows) == 3
    
    # Create a map of expected results
    expected = {
        "Engineering": {"count": 2, "avg_salary": (80000 + 70000) / 2},
        "Marketing": {"count": 2, "avg_salary": (75000 + 85000) / 2},
        "HR": {"count": 1, "avg_salary": 90000}
    }
    
    # Verify results
    for row in rows:
        dept_name = row["d.name"]
        count = row["COUNT(*)"]
        avg_salary = row["AVG(e.salary)"]
        
        assert count == expected[dept_name]["count"]
        assert avg_salary == expected[dept_name]["avg_salary"]

def test_join_with_ordering(setup_fk_tables):
    """Test a join with ordering by a column from the joined table"""
    _, parser, validator, executor = setup_fk_tables
    
    # Get employees ordered by department name
    order_query = parser.parse(
        "SELECT e.name, d.name "
        "FROM employees AS e, departments AS d "
        "WHERE e.dept_id = d.id "
        "ORDER BY d.name ASC, e.name DESC"
    )
    validator.validate(order_query)
    rows, _ = executor.run(order_query)
    
    # Should return all 5 employees
    assert len(rows) == 5
    
    # Verify ordering: first by department (Engineering, HR, Marketing), 
    # then by employee name in descending order
    expected_order = [
        ("Bob", "Engineering"),
        ("Alice", "Engineering"),
        ("Eve", "HR"),
        ("David", "Marketing"),
        ("Charlie", "Marketing")
    ]
    
    for i, (expected_emp, expected_dept) in enumerate(expected_order):
        assert rows[i]["e.name"] == expected_emp
        assert rows[i]["d.name"] == expected_dept

def test_insert_multiple_values(clean_catalog, parser, validator, executor):
    """Test inserting multiple rows in a single INSERT statement."""
    # Create a simple table
    create_query_str = "CREATE TABLE multi_insert_test (id INT, name STR, PRIMARY KEY(id))"
    create_query = parser.parse(create_query_str)
    validator.validate(create_query)
    executor.run(create_query)

    # Insert multiple values in a single query
    insert_query_str = "INSERT INTO multi_insert_test (id, name) VALUES (1, 'Row1'), (2, 'Row2'), (3, 'Row3')"
    insert_query = parser.parse(insert_query_str)
    validator.validate(insert_query)
    executor.run(insert_query)

    # Verify the count of inserted rows
    count_query = parser.parse("SELECT COUNT(*) FROM multi_insert_test")
    validator.validate(count_query)
    rows, _ = executor.run(count_query)
    assert rows[0]["COUNT(*)"] == 3

    # Verify the actual inserted data
    select_query = parser.parse("SELECT id, name FROM multi_insert_test ORDER BY id ASC")
    validator.validate(select_query)
    rows, _ = executor.run(select_query)
    print(rows)
    assert len(rows) == 3
    assert rows[0]["multi_insert_test.id"] == 1 and rows[0]["multi_insert_test.name"] == 'Row1'
    assert rows[1]["multi_insert_test.id"] == 2 and rows[1]["multi_insert_test.name"] == 'Row2'
    assert rows[2]["multi_insert_test.id"] == 3 and rows[2]["multi_insert_test.name"] == 'Row3'
