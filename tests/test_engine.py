import pytest
from pathlib import Path

from catalog import Catalog
from parser import SQLParser, QueryValidator
from engine import Executor
from storage.heap_file import HeapFile

@pytest.fixture()
def setup_db(tmp_path):
    data_dir = tmp_path / "data"
    catalog = Catalog()
    #parser = SQLParser(catalog)
    parser = SQLParser()
    validator = QueryValidator(catalog)
    exec_ = Executor(catalog, data_dir)
    # build sample data
    catalog.create_table("people", [("id", "INT"), ("name", "STR"), ("age", "INT")], primary_key="id")
    catalog.create_table("orders", [("id", "INT"), ("person_id", "INT"), ("amount", "INT")], primary_key="id")
    people = HeapFile(catalog, data_dir, "people")
    orders = HeapFile(catalog, data_dir, "orders")
    people.insert(1, "Alice", 25)
    people.insert(2, "Bob", 30)
    people.insert(3, "Charlie", 22)
    orders.insert(100, 1, 50)
    orders.insert(200, 2, 75)
    orders.insert(300, 1, 25)
    orders.insert(400, 3, 100)
    
    yield catalog, parser, validator, exec_
    
    # cleanup
    try:
        catalog.drop_table("orders")
        catalog.drop_table("people")
    except Exception as e:
        print(f"Cleanup error: {e}")
    finally:
        catalog.reset()

def test_single_table_where(setup_db): #1
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE id = 2")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows == [{"people.id": 2, "people.name": "Bob"}]

def test_two_table_join(setup_db): #2
    _, parser, validator, exec_ = setup_db
    sql = (
        "SELECT p.id, o.amount FROM people AS p, orders AS o "
        "WHERE p.id = o.person_id"
    )
    q = parser.parse(sql)
    validator.validate(q)
    rows, _ = exec_.run(q)
    expected = [
        {"p.id": 1, "o.amount": 50},
        {"p.id": 1, "o.amount": 25},
        {"p.id": 2, "o.amount": 75},
        {"p.id": 3, "o.amount": 100},
    ]
    # sort for comparison
    sort_key = lambda r: (r.get("p.id"), r.get("o.amount"))
    assert sorted(rows, key=sort_key) == sorted(expected, key=sort_key)

def test_single_table_where_with_logical_ops(setup_db): #3
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE id = 2 AND age > 25")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows == [{"people.id": 2, "people.name": "Bob"}]

def test_single_table_where_greater_than(setup_db): #4
    """test greater than comparison operator."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE age > 25")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.name"] == "Bob"

def test_single_table_where_or_condition(setup_db): #5
    """Test OR logical operator."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE age > 28 OR id = 1")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 2
    names = sorted([row["people.name"] for row in rows])
    assert names == ["Alice", "Bob"]

def test_complex_logical_expression(setup_db): #6
    """Test complex logical expression (AND with OR)."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE (id = 1 OR age > 28) AND name != 'Charlie'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 2
    
def test_select_all_columns(setup_db): #7
    """Test SELECT * functionality."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT * FROM people WHERE id = 1")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert "people.id" in rows[0]
    assert "people.name" in rows[0]
    assert "people.age" in rows[0]
    assert rows[0]["people.name"] == "Alice"

def test_not_equal_condition(setup_db): #8
    """Test != comparison operator."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE name != 'Alice'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 2
    names = sorted([row["people.name"] for row in rows])
    assert names == ["Bob", "Charlie"]

def test_multiple_conditions_on_join(setup_db): #9
    """Test multiple conditions in a join."""
    _, parser, validator, exec_ = setup_db
    sql = (
        "SELECT p.id, o.amount FROM people AS p, orders AS o "
        "WHERE p.id = o.person_id AND o.amount > 30"
    )
    q = parser.parse(sql)
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 3
    amounts = sorted([row["o.amount"] for row in rows])
    assert amounts == [50, 75, 100]

def test_order_filtering_after_join(setup_db): #10
    """Test filtering orders after join."""
    _, parser, validator, exec_ = setup_db
    sql = (
        "SELECT p.name, o.amount FROM people AS p, orders AS o "
        "WHERE p.id = o.person_id AND o.amount < 30"
    )
    q = parser.parse(sql)
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["p.name"] == "Alice"
    assert rows[0]["o.amount"] == 25

def test_empty_result_set(setup_db): #11
    """Test query that returns no results."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT id, name FROM people WHERE age > 100")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 0

# Tests for aggregation functions
def test_count_all(setup_db): #12
    """Test COUNT(*) aggregation."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT COUNT(*) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["COUNT(*)"] == 3

def test_count_with_predicate(setup_db):
    """Test COUNT(*) with a WHERE clause."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT COUNT(*) FROM people WHERE age > 25")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["COUNT(*)"] == 1

def test_sum_aggregation(setup_db):
    """Test SUM aggregation."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT SUM(age) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["SUM(people.age)"] == 77  # 25 + 30 + 22

def test_avg_aggregation(setup_db):
    """Test AVG aggregation."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT AVG(age) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["AVG(people.age)"] == 77 / 3

def test_min_max_aggregation(setup_db):
    """Test MIN and MAX aggregations."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT MIN(age), MAX(age) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["MIN(people.age)"] == 22
    assert rows[0]["MAX(people.age)"] == 30

def test_multiple_aggregations(setup_db):
    """Test multiple aggregation functions in one query."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT COUNT(*), SUM(amount), AVG(amount), MIN(amount), MAX(amount) FROM orders")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["COUNT(*)"] == 4
    assert rows[0]["SUM(orders.amount)"] == 250  # 50 + 75 + 25 + 100
    assert rows[0]["AVG(orders.amount)"] == 250 / 4
    assert rows[0]["MIN(orders.amount)"] == 25
    assert rows[0]["MAX(orders.amount)"] == 100

def test_aggregation_with_join(setup_db):
    """Test aggregation with join."""
    _, parser, validator, exec_ = setup_db
    sql = (
        "SELECT COUNT(*), SUM(o.amount) FROM people AS p, orders AS o "
        "WHERE p.id = o.person_id AND p.name = 'Alice'"
    )
    q = parser.parse(sql)
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["COUNT(*)"] == 2
    assert rows[0]["SUM(o.amount)"] == 75  # 50 + 25

def test_empty_aggregation(setup_db):
    """Test aggregation on empty result set."""
    _, parser, validator, exec_ = setup_db
    q = parser.parse("SELECT COUNT(*), SUM(age) FROM people WHERE age > 100")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["COUNT(*)"] == 0
    assert rows[0]["SUM(people.age)"] is None  # No values to sum

# Tests for INSERT operations
def test_basic_insert(setup_db):
    """Test basic INSERT operation."""
    _, parser, validator, exec_ = setup_db
    # Insert a new person
    q = parser.parse("INSERT INTO people VALUES (4, 'David', 35)")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "INSERT"
    assert result[0]["rows_affected"] == 1
    
    # Verify the insert worked by querying
    q = parser.parse("SELECT * FROM people WHERE id = 4")
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.id"] == 4
    assert rows[0]["people.name"] == "David"
    assert rows[0]["people.age"] == 35

def test_insert_with_column_list(setup_db):
    """Test INSERT with specified columns."""
    _, parser, validator, exec_ = setup_db
    # Insert with specified columns
    q = parser.parse("INSERT INTO people (id, name, age) VALUES (5, 'Eva', 28)")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "INSERT"
    
    # Verify the insert worked
    q = parser.parse("SELECT * FROM people WHERE id = 5")
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.name"] == "Eva"
    assert rows[0]["people.age"] == 28

def test_insert_with_reordered_columns(setup_db):
    """Test INSERT with reordered columns."""
    _, parser, validator, exec_ = setup_db
    # Insert with reordered columns
    q = parser.parse("INSERT INTO people (name, id, age) VALUES ('Frank', 6, 42)")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "INSERT"
    
    # Verify the insert worked
    q = parser.parse("SELECT * FROM people WHERE id = 6")
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.name"] == "Frank"
    assert rows[0]["people.age"] == 42

# Tests for DELETE operations
def test_delete_with_condition(setup_db):
    """Test DELETE with a WHERE condition."""
    _, parser, validator, exec_ = setup_db
    # First, verify Alice exists
    q = parser.parse("SELECT * FROM people WHERE name = 'Alice'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    
    # Delete Alice
    q = parser.parse("DELETE FROM people WHERE name = 'Alice'")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "DELETE"
    assert result[0]["rows_affected"] == 1
    
    # Verify Alice is gone
    q = parser.parse("SELECT * FROM people WHERE name = 'Alice'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 0
    
    # Verify Bob and Charlie still exist
    q = parser.parse("SELECT COUNT(*) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows[0]["COUNT(*)"] == 2

def test_delete_all(setup_db):
    """Test DELETE without a WHERE condition (delete all rows)."""
    _, parser, validator, exec_ = setup_db
    # Delete all orders
    q = parser.parse("DELETE FROM orders")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "DELETE"
    assert result[0]["rows_affected"] == 4
    
    # Verify all orders are gone
    q = parser.parse("SELECT COUNT(*) FROM orders")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows[0]["COUNT(*)"] == 0
    
    # Verify people table is unaffected
    q = parser.parse("SELECT COUNT(*) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows[0]["COUNT(*)"] == 3

def test_delete_with_complex_condition(setup_db):
    """Test DELETE with a complex condition."""
    _, parser, validator, exec_ = setup_db
    # Delete people older than 25
    q = parser.parse("DELETE FROM people WHERE age > 25")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "DELETE"
    assert result[0]["rows_affected"] == 1  # Bob 
    
    # Verify Alice and Charlie remain
    q = parser.parse("SELECT * FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 2
    assert rows[0]["people.name"] in ["Alice", "Charlie"]

# Tests for UPDATE operations
def test_update_single_row(setup_db):
    """Test UPDATE on a single row."""
    _, parser, validator, exec_ = setup_db
    # Update Alice's age
    q = parser.parse("UPDATE people SET age = 26 WHERE name = 'Alice'")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "UPDATE"
    assert result[0]["rows_affected"] == 1
    
    # Verify the update worked
    q = parser.parse("SELECT age FROM people WHERE name = 'Alice'")
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.age"] == 26

def test_update_multiple_rows(setup_db):
    """Test UPDATE on multiple rows."""
    _, parser, validator, exec_ = setup_db
    # Increase everyone's age by 1 (using a complex update logic)
    q = parser.parse("UPDATE people SET age = 31 WHERE age = 30")
    validator.validate(q)
    result, _ = exec_.run(q)
    
    # Verify the update worked
    q = parser.parse("SELECT age FROM people WHERE name = 'Bob'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.age"] == 31

def test_update_multiple_columns(setup_db):
    """Test updating multiple columns in one statement."""
    _, parser, validator, exec_ = setup_db
    # Update both name and age
    q = parser.parse("UPDATE people SET name = 'Alice2', age = 27 WHERE id = 1")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "UPDATE"
    assert result[0]["rows_affected"] == 1
    
    # Verify both updates worked
    q = parser.parse("SELECT name, age FROM people WHERE id = 1")
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.name"] == "Alice2"
    assert rows[0]["people.age"] == 27

def test_update_all_rows(setup_db):
    """Test updating all rows (no WHERE clause)."""
    _, parser, validator, exec_ = setup_db
    # Reset all ages to 30
    q = parser.parse("UPDATE people SET age = 30")
    validator.validate(q)
    result, _ = exec_.run(q)
    assert result[0]["operation"] == "UPDATE"
    assert result[0]["rows_affected"] == 3  # All three people
    
    # Verify all ages are now 30
    q = parser.parse("SELECT age FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 3
    assert all(row["people.age"] == 30 for row in rows)

def test_compound_dml_operations(setup_db):
    """Test a sequence of INSERT, UPDATE, and DELETE operations."""
    _, parser, validator, exec_ = setup_db
    
    # 1. Insert a new person
    q = parser.parse("INSERT INTO people VALUES (4, 'David', 35)")
    validator.validate(q)
    exec_.run(q)
    
    # 2. Update their age
    q = parser.parse("UPDATE people SET age = 36 WHERE name = 'David'")
    validator.validate(q)
    exec_.run(q)
    
    # 3. Delete a different person
    q = parser.parse("DELETE FROM people WHERE name = 'Charlie'")
    validator.validate(q)
    exec_.run(q)
    
    # Verify all operations worked
    q = parser.parse("SELECT COUNT(*) FROM people")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert rows[0]["COUNT(*)"] == 3  # Alice, Bob, David
    
    q = parser.parse("SELECT * FROM people WHERE name = 'David'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 1
    assert rows[0]["people.age"] == 36
    
    q = parser.parse("SELECT * FROM people WHERE name = 'Charlie'")
    validator.validate(q)
    rows, _ = exec_.run(q)
    assert len(rows) == 0