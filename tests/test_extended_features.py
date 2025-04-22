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
    
    # Create tables
    catalog.create_table("students", [
        ("id", "INT"), 
        ("name", "STR"), 
        ("age", "INT"), 
        ("major", "STR"), 
        ("gpa", "INT")
    ], primary_key="id")
    
    catalog.create_table("courses", [
        ("id", "INT"), 
        ("name", "STR"), 
        ("department", "STR"), 
        ("credits", "INT")
    ], primary_key="id")
    
    catalog.create_table("enrollments", [
        ("id", "INT"), 
        ("student_id", "INT"), 
        ("course_id", "INT"), 
        ("grade", "INT"), 
        ("semester", "STR")
    ], primary_key="id")
    
    # Create heap files
    students = HeapFile(catalog, data_dir, "students")
    courses = HeapFile(catalog, data_dir, "courses")
    enrollments = HeapFile(catalog, data_dir, "enrollments")
    
    # Insert sample data for students
    students.insert(1, "Alice", 20, "Computer Science", 85)
    students.insert(2, "Bob", 22, "Mathematics", 90)
    students.insert(3, "Charlie", 21, "Computer Science", 78)
    students.insert(4, "David", 23, "Physics", 92)
    students.insert(5, "Eva", 20, "Mathematics", 88)
    
    # Insert sample data for courses
    courses.insert(101, "Intro to Programming", "Computer Science", 3)
    courses.insert(102, "Data Structures", "Computer Science", 4)
    courses.insert(103, "Calculus I", "Mathematics", 4)
    courses.insert(104, "Quantum Physics", "Physics", 5)
    courses.insert(105, "Linear Algebra", "Mathematics", 3)
    
    # Insert sample data for enrollments
    enrollments.insert(1, 1, 101, 90, "Fall 2023")
    enrollments.insert(2, 1, 102, 85, "Fall 2023")
    enrollments.insert(3, 2, 103, 92, "Fall 2023")
    enrollments.insert(4, 2, 105, 88, "Fall 2023")
    enrollments.insert(5, 3, 101, 75, "Fall 2023")
    enrollments.insert(6, 3, 102, 80, "Fall 2023")
    enrollments.insert(7, 4, 104, 95, "Fall 2023")
    enrollments.insert(8, 5, 103, 85, "Fall 2023")
    enrollments.insert(9, 5, 105, 90, "Fall 2023")
    enrollments.insert(10, 1, 103, 82, "Spring 2023")
    
    yield catalog, parser, validator, exec_
    
    # cleanup
    try:
        catalog.drop_table("enrollments")
        catalog.drop_table("courses")
        catalog.drop_table("students")
    except Exception as e:
        print(f"Cleanup error: {e}")
    finally:
        catalog.reset()

# Tests for ORDER BY
def test_order_by_single_column(setup_db):
    """Test ORDER BY with a single column"""
    _, parser, validator, exec_ = setup_db
    
    # Test ascending order (default)
    q = parser.parse("SELECT name, age FROM students ORDER BY age")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Check order is ascending by age
    ages = [row["students.age"] for row in rows]
    assert ages == sorted(ages)
    assert len(rows) == 5
    
    # Test descending order
    q = parser.parse("SELECT name, age FROM students ORDER BY age DESC")
    rows, _ = exec_.run(q)
    # Check order is descending by age
    ages = [row["students.age"] for row in rows]
    assert ages == sorted(ages, reverse=True)
    assert len(rows) == 5

def test_order_by_multiple_columns(setup_db):
    """Test ORDER BY with multiple columns"""
    _, parser, validator, exec_ = setup_db
    
    # Order by major (ASC) and then by age (DESC)
    q = parser.parse("SELECT name, major, age FROM students ORDER BY major, age DESC")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Group by major and check that within each group, ages are in descending order
    current_major = None
    for i, row in enumerate(rows):
        if current_major != row["students.major"]:
            current_major = row["students.major"]
            current_age = 999  # Start with a high value
            
        # Within a major group, age should be in descending order
        age = row["students.age"]
        assert age <= current_age
        current_age = age
        
    # Make sure we have all 5 students
    assert len(rows) == 5

def test_order_by_with_where(setup_db):
    """Test ORDER BY with WHERE clause"""
    _, parser, validator, exec_ = setup_db
    
    # Get students with age > 20, ordered by GPA
    q = parser.parse("SELECT name, age, gpa FROM students WHERE age > 20 ORDER BY gpa DESC")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Check filtering worked
    assert all(row["students.age"] > 20 for row in rows)
    
    # Check ordering by GPA is descending
    gpas = [row["students.gpa"] for row in rows]
    assert gpas == sorted(gpas, reverse=True)
    
    # Should have 3 students (Bob, Charlie, David)
    assert len(rows) == 3

# Tests for GROUP BY
def test_group_by_with_count(setup_db):
    """Test GROUP BY with COUNT aggregation"""
    _, parser, validator, exec_ = setup_db
    
    # Count students by major
    q = parser.parse("SELECT major, COUNT(*) FROM students GROUP BY major")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Convert to dict for easier checking
    counts = {row["students.major"]: row["COUNT(*)"] for row in rows}
    
    # Check counts by major
    assert counts["Computer Science"] == 2
    assert counts["Mathematics"] == 2
    assert counts["Physics"] == 1
    
    # Should have one row per major
    assert len(rows) == 3

def test_group_by_with_multiple_aggregates(setup_db):
    """Test GROUP BY with multiple aggregate functions"""
    _, parser, validator, exec_ = setup_db
    
    # Get average, min, and max GPA by major
    q = parser.parse("SELECT major, AVG(gpa), MIN(gpa), MAX(gpa) FROM students GROUP BY major")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should have one row per major
    assert len(rows) == 3
    
    # Find the Computer Science major row
    cs_row = next(row for row in rows if row["students.major"] == "Computer Science")
    
    # Check aggregations for Computer Science
    assert cs_row["AVG(students.gpa)"] == (85 + 78) / 2
    assert cs_row["MIN(students.gpa)"] == 78
    assert cs_row["MAX(students.gpa)"] == 85

def test_group_by_with_order_by(setup_db):
    """Test GROUP BY with ORDER BY"""
    _, parser, validator, exec_ = setup_db
    
    # Get average GPA by major, ordered by the average
    q = parser.parse("SELECT major, AVG(gpa) FROM students GROUP BY major ORDER BY AVG(gpa) DESC")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Check order is descending by avg GPA
    avgs = [row["AVG(students.gpa)"] for row in rows]
    assert avgs == sorted(avgs, reverse=True)
    
    # First major should be Physics (with highest avg GPA)
    assert rows[0]["students.major"] == "Physics"

# Tests for HAVING
def test_having_clause(setup_db):
    """Test HAVING clause to filter groups"""
    _, parser, validator, exec_ = setup_db
    
    # Get majors with average GPA > 85
    q = parser.parse("SELECT major, AVG(gpa) FROM students GROUP BY major HAVING AVG(gpa) > 85")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Check all returned groups have avg GPA > 85
    assert all(row["AVG(students.gpa)"] > 85 for row in rows)
    
    # Should only have Physics and Mathematics majors
    majors = [row["students.major"] for row in rows]
    assert "Physics" in majors
    assert "Mathematics" in majors
    assert "Computer Science" not in majors
    assert len(rows) == 2

def test_complex_having(setup_db):
    """Test HAVING with more complex conditions"""
    _, parser, validator, exec_ = setup_db
    
    # Get majors with average GPA > 85 and more than 1 student
    q = parser.parse("SELECT major, COUNT(*), AVG(gpa) FROM students GROUP BY major HAVING COUNT(*) > 1 AND AVG(gpa) > 85")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should only return Mathematics
    assert len(rows) == 1
    assert rows[0]["students.major"] == "Mathematics"
    assert rows[0]["COUNT(*)"] == 2
    assert rows[0]["AVG(students.gpa)"] > 85

# Tests for LIMIT
def test_limit_simple(setup_db):
    """Test LIMIT clause"""
    _, parser, validator, exec_ = setup_db
    
    # Get only first 3 students
    q = parser.parse("SELECT id, name FROM students LIMIT 3")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should return exactly 3 rows
    assert len(rows) == 3
    
    # Should be the first 3 students (IDs 1, 2, 3)
    ids = [row["students.id"] for row in rows]
    assert set(ids) == {1, 2, 3}

def test_limit_with_order_by(setup_db):
    """Test LIMIT with ORDER BY"""
    _, parser, validator, exec_ = setup_db
    
    # Get the 2 youngest students
    q = parser.parse("SELECT name, age FROM students ORDER BY age LIMIT 2")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should return 2 rows
    assert len(rows) == 2
    
    # Should be the 2 youngest students (age 20)
    assert all(row["students.age"] == 20 for row in rows)
    names = [row["students.name"] for row in rows]
    assert set(names) == {"Alice", "Eva"}

def test_limit_exceeding_rows(setup_db):
    """Test LIMIT that exceeds available rows"""
    _, parser, validator, exec_ = setup_db
    
    # Try to get 10 students when only 5 exist
    q = parser.parse("SELECT id, name FROM students LIMIT 10")
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should return all 5 available rows
    assert len(rows) == 5

# Combination tests
def test_all_features_combined(setup_db):
    """Test combining all features: WHERE, GROUP BY, HAVING, ORDER BY, LIMIT"""
    _, parser, validator, exec_ = setup_db
    
    # Complex query using all features
    q = parser.parse("""
        SELECT c.department, COUNT(*), AVG(e.grade)
        FROM courses AS c, enrollments AS e
        WHERE c.id = e.course_id AND e.grade > 80
        GROUP BY c.department
        HAVING COUNT(*) >= 2
        ORDER BY AVG(e.grade) DESC
        LIMIT 2
    """)
    validator.validate(q)
    rows, _ = exec_.run(q)
    
    # Should have at most 2 rows
    assert len(rows) <= 2
    
    # Each department should have at least 2 enrollments with grade > 80
    assert all(row["COUNT(*)"] >= 2 for row in rows)
    
    # Average grades should be in descending order
    avgs = [row["AVG(e.grade)"] for row in rows]
    assert avgs == sorted(avgs, reverse=True)
    
    # All grades in the calculation should be > 80
    assert all(row["AVG(e.grade)"] > 80 for row in rows)

def test_parser_errors(setup_db):
    """Test that parser catches errors correctly for new clauses"""
    _, parser, validator, _ = setup_db
    
    # Test GROUP BY without required column in SELECT
    with pytest.raises(Exception):
        parser.parse("SELECT name FROM students GROUP BY major")
        validator.validate(q)
    
    # Test HAVING without GROUP BY
    with pytest.raises(Exception):
        q = parser.parse("SELECT name FROM students HAVING COUNT(*) > 1")
        validator.validate(q)
    
    # Test negative LIMIT
    with pytest.raises(Exception):
        q = parser.parse("SELECT name FROM students LIMIT -1")
        validator.validate(q)
    
    # Test ORDER BY with invalid column
    with pytest.raises(Exception):
        q = parser.parse("SELECT name FROM students ORDER BY non_existent_column") 
        validator.validate(q)