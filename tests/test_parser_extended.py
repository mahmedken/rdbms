import pytest
from pyparsing import ParseException
from catalog import Catalog
from parser import SQLParser, QueryValidator        

@pytest.fixture(autouse=True)
def clean_catalog(tmp_path, monkeypatch):
    """each test gets a new catalog in a tmp dir"""
    cat_path = tmp_path / "cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    catalog = Catalog()
    yield catalog
    catalog.reset()

def setup_test_schema(catalog):
    """Set up a test schema with tables and columns for testing"""
    catalog.create_table(
        "students", 
        [
            ("id", "INT"), 
            ("name", "STR"), 
            ("age", "INT"), 
            ("major", "STR"), 
            ("gpa", "INT")
        ], 
        primary_key="id"
    )

    catalog.create_table(
        "courses", 
        [
            ("id", "INT"), 
            ("name", "STR"), 
            ("department", "STR"), 
            ("credits", "INT")
        ], 
        primary_key="id"
    )

# ORDER BY tests
def test_parse_order_by_single_column(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT id, name FROM students ORDER BY age")
    
    assert result
    assert "order_by" in result
    assert len(result.order_by) == 1
    assert result.order_by[0][0].column == "age"
    assert result.order_by[0].direction == "ASC"  # Default direction is ASC

def test_parse_order_by_with_direction(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # Test ASC
    result = parser.parse("SELECT id, name FROM students ORDER BY age ASC")
    validator.validate(result)
    assert result.order_by[0].direction == "ASC"
    
    # Test DESC
    result = parser.parse("SELECT id, name FROM students ORDER BY gpa DESC")
    validator.validate(result)
    assert result.order_by[0].direction == "DESC"

def test_parse_order_by_multiple_columns(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT id, name FROM students ORDER BY major ASC, age DESC")
    validator.validate(result)
    assert len(result.order_by) == 2
    assert result.order_by[0][0].column == "major"
    assert result.order_by[0].direction == "ASC"
    assert result.order_by[1][0].column == "age"
    assert result.order_by[1].direction == "DESC"

def test_parse_order_by_with_qualified_column(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT s.id, s.name FROM students AS s ORDER BY s.age DESC")
    validator.validate(result)
    assert result.order_by[0][0].table[0] == "s"
    assert result.order_by[0][0].column == "age"
    assert result.order_by[0].direction == "DESC"

# GROUP BY tests
def test_parse_group_by_single_column(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, COUNT(*) FROM students GROUP BY major")
    validator.validate(result)
    assert result
    assert "group_by" in result
    assert len(result.group_by) == 1
    assert result.group_by[0].column == "major"

def test_parse_group_by_multiple_columns(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, age, COUNT(*) FROM students GROUP BY major, age")
    
    assert len(result.group_by) == 2
    assert result.group_by[0].column == "major"
    assert result.group_by[1].column == "age"

def test_group_by_with_qualified_column(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT s.major, COUNT(*) FROM students AS s GROUP BY s.major")
    validator.validate(result)
    assert result.group_by[0].table[0] == "s"
    assert result.group_by[0].column == "major"

def test_group_by_with_aggregation_functions(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, AVG(gpa), MIN(age), MAX(age) FROM students GROUP BY major")
    validator.validate(result)
    # Check aggregation functions in SELECT
    assert len(result.columns) == 4  # major + 3 aggregations
    assert result.columns[0].column == "major"
    
    # Check AVG aggregation
    assert result.columns[1].getName() == "aggregation"
    assert result.columns[1].function == "AVG"
    assert result.columns[1].argument[0].column == "gpa"
    
    # Check MIN aggregation
    assert result.columns[2].getName() == "aggregation"
    assert result.columns[2].function == "MIN"
    assert result.columns[2].argument[0].column == "age"
    
    # Check MAX aggregation
    assert result.columns[3].getName() == "aggregation"
    assert result.columns[3].function == "MAX"
    assert result.columns[3].argument[0].column == "age"

# HAVING tests
def test_parse_having_simple(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, COUNT(*) FROM students GROUP BY major HAVING COUNT(*) > 1")
    validator.validate(result)
    assert result
    assert "having" in result
    assert result.having  # Ensure having clause was parsed

def test_parse_having_with_aggregation(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, AVG(gpa) FROM students GROUP BY major HAVING AVG(gpa) > 85")
    validator.validate(result)
    assert result
    assert "having" in result
    assert result.having  # Ensure having clause was parsed

def test_parse_having_with_complex_condition(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT major, COUNT(*), AVG(gpa) FROM students GROUP BY major HAVING COUNT(*) > 1 AND AVG(gpa) > 85")
    validator.validate(result)
    assert result
    assert "having" in result
    assert result.having  # Ensure having clause was parsed

def test_having_without_group_by_fails(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    with pytest.raises(ParseException): 
        q = parser.parse("SELECT major, COUNT(*) FROM students HAVING COUNT(*) > 1")
        validator.validate(q)

# LIMIT tests
def test_parse_limit(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT id, name FROM students LIMIT 5")
    validator.validate(result)
    assert result
    assert "limit" in result
    assert result.limit == 5

def test_parse_limit_zero(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    result = parser.parse("SELECT id, name FROM students LIMIT 0")
    validator.validate(result)
    assert result.limit == 0

def test_parse_negative_limit_fails(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    with pytest.raises(ParseException):
        q = parser.parse("SELECT id, name FROM students LIMIT -5")
        validator.validate(q)

# Combined clause tests
def test_parse_all_clauses_together(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    query = """
    SELECT major, COUNT(*), AVG(gpa)
    FROM students
    WHERE age > 20
    GROUP BY major
    HAVING COUNT(*) > 1
    ORDER BY AVG(gpa) DESC
    LIMIT 2
    """
    
    result = parser.parse(query)
    
    assert result
    assert "where" in result
    assert "group_by" in result
    assert "having" in result
    assert "order_by" in result
    assert "limit" in result
    
    assert len(result.group_by) == 1
    assert result.group_by[0].column == "major"
    
    assert result.order_by[0].direction == "DESC"
    
    assert result.limit == 2

def test_parse_clause_order(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # Incorrect order: LIMIT before ORDER BY
    with pytest.raises(ParseException):
        q = parser.parse("""
        SELECT major, COUNT(*)
        FROM students
        GROUP BY major
        LIMIT 5
        ORDER BY major
        """)
        validator.validate(q)
    
    # Incorrect order: HAVING before GROUP BY
    with pytest.raises(ParseException):
        q = parser.parse("""
        SELECT major, COUNT(*)
        FROM students
        HAVING COUNT(*) > 1
        GROUP BY major
        """)
        validator.validate(q)
    # Incorrect order: ORDER BY before GROUP BY
    with pytest.raises(ParseException):
        q = parser.parse("""
        SELECT major, COUNT(*)
        FROM students
        ORDER BY COUNT(*)
        GROUP BY major
        """)
        validator.validate(q)

def test_validation_select_columns_with_group_by(clean_catalog):
    setup_test_schema(clean_catalog)
    parser = SQLParser()
    validator = QueryValidator(clean_catalog)
    
    # Valid: column in SELECT is also in GROUP BY
    result = parser.parse("SELECT major, COUNT(*) FROM students GROUP BY major")
    validator.validate(result)
    assert result
    
    # Invalid: column in SELECT not in GROUP BY
    with pytest.raises(ParseException):
        q = parser.parse("SELECT name, COUNT(*) FROM students GROUP BY major")
        validator.validate(q)
    
    # Invalid: cannot use * with GROUP BY
    with pytest.raises(ParseException):
        q = parser.parse("SELECT * FROM students GROUP BY major")
        validator.validate(q)
    
    # Valid: all columns in SELECT are aggregates or in GROUP BY
    result = parser.parse("SELECT major, age, COUNT(*), AVG(gpa) FROM students GROUP BY major, age")
    validator.validate(result)
    assert result 