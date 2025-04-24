import pytest
from pathlib import Path

from pyparsing import ParseException
from catalog import Catalog, CatalogError, UnknownTableError
from parser import SQLParser
from optimizer import QueryOptimizer # Import the optimizer

# Fixture to provide a clean catalog for each test
@pytest.fixture(autouse=True)
def clean_catalog(tmp_path, monkeypatch):
    """Each test gets a new catalog in a tmp dir."""
    cat_path = tmp_path / "opt_cat.json"
    monkeypatch.setenv("RDBMS_CATALOG", str(cat_path))
    catalog = Catalog()
    yield catalog
    # No need to reset if each test gets a new file, but good practice
    try:
        catalog.reset()
    except Exception:
         pass # Ignore errors if catalog was already deleted or empty

# Fixture for the SQLParser
@pytest.fixture
def parser():
    return SQLParser()

# Fixture for the QueryOptimizer
@pytest.fixture
def optimizer(clean_catalog): # Depends on the clean catalog
    return QueryOptimizer(clean_catalog)

# Helper function to create tables for join tests
def setup_join_tables(catalog: Catalog, size: str, indexed: bool):
    """Helper to create table schemas for join tests."""
    table_prefix = f"{size}_"
    table1 = f"{table_prefix}table1"
    table2 = f"{table_prefix}table2"

    # Define columns using lists of tuples for create_table
    cols1_list = [('id', 'INT'), ('data1', 'STR')]
    cols2_list = [('id', 'INT'), ('fkid', 'INT'), ('data2', 'STR')] # fkid references table1.id

    pk1 = 'id'
    pk2 = 'id'

    fk2 = {'fkid': (table1, 'id')}

    # Define desired indexes
    indexes1_cols = {'data1'} if indexed else set()
    indexes2_cols = {'fkid', 'data2'} if indexed else set()

    # Adjust column count for size estimation (if using the simple optimizer model)
    if size == "large":
         cols1_list.extend([(f'dummy{i}', 'INT') for i in range(10)])
         cols2_list.extend([(f'dummy{i}', 'INT') for i in range(10)])

    # Create tables first
    catalog.create_table(table1, cols1_list, primary_key=pk1)
    catalog.create_table(table2, cols2_list, primary_key=pk2, foreign_keys=fk2)
    
    # Now, create the indexes separately
    for col in indexes1_cols:
        if col != pk1: # PK is already indexed automatically
            catalog.create_index(table1, col)
    for col in indexes2_cols:
         if col != pk2:
            catalog.create_index(table2, col)
            
    return table1, table2


# --- Join Method Selection Tests ---

def test_join_method_small_tables(clean_catalog, parser, optimizer):
    """Test that Nested Loop Join is chosen for small tables."""
    t1, t2 = setup_join_tables(clean_catalog, size="small", indexed=False)
    query_str = f"SELECT * FROM {t1}, {t2} WHERE {t1}.id = {t2}.fkid"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    
    # Accessing the added attribute - adjust based on how optimizer adds it
    assert optimized.get('join_method') == 'nested_loop'

def test_join_method_large_tables_no_index(clean_catalog, parser, optimizer):
    """Test that Sort Merge Join is chosen for large tables without relevant indices."""
    t1, t2 = setup_join_tables(clean_catalog, size="large", indexed=False)
    query_str = f"SELECT * FROM {t1}, {t2} WHERE {t1}.id = {t2}.fkid"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    assert optimized.get('join_method') == 'sort_merge'

def test_join_method_large_tables_with_index(clean_catalog, parser, optimizer):
    """Test that Sort Merge Join is chosen for large tables even with indices (cost model check)."""
    # Note: Current cost model reduces SMJ cost if *any* index exists, not necessarily on join key.
    t1, t2 = setup_join_tables(clean_catalog, size="large", indexed=True)
    query_str = f"SELECT * FROM {t1}, {t2} WHERE {t1}.id = {t2}.fkid"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    assert optimized.get('join_method') == 'sort_merge'


# --- Condition Reordering Tests ---

@pytest.fixture
def setup_condition_table(clean_catalog):
    """Setup a table used for condition optimization tests."""
    table_name = "cond_test_table"
    cols = [('pk', 'INT'), ('col_int', 'INT'), ('col_str', 'STR')]
    index_col = 'col_str'
    
    # Create table first
    clean_catalog.create_table(table_name, cols, primary_key='pk')
    
    # Create the desired index separately
    if index_col != 'pk': # PK is auto-indexed
        clean_catalog.create_index(table_name, index_col)
        
    return table_name

def test_condition_reorder_and(setup_condition_table, parser, optimizer):
    """Test AND conditions are reordered (most selective first)."""
    table = setup_condition_table
    # Equality (=) is estimated as more selective (0.1) than range (>) (0.3)
    query_str = f"SELECT * FROM {table} WHERE col_int > 100 AND pk = 5"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    
    optimized_where = optimized['where'][1]
    # Expected: pk = 5 should be the left operand (condition[0]) after optimization
    print(f"Optimized WHERE: {optimized_where}")
    assert optimized_where[1].upper() == "AND"
    assert optimized_where[0][0].column == 'pk' # Left part of the equality check
    assert optimized_where[0][1] == '='
    assert optimized_where[2][0].column == 'col_int' # Right part of the range check
    assert optimized_where[2][1] == '>'

def test_condition_reorder_and_reverse_input(setup_condition_table, parser, optimizer):
    """Test AND conditions are reordered even if input order is reversed."""
    table = setup_condition_table
    # Equality (=) is estimated as more selective (0.1) than range (>) (0.3)
    query_str = f"SELECT * FROM {table} WHERE pk = 5 AND col_int > 100" # Reversed input order
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    
    optimized_where = optimized['where'][1]
    # Expected: pk = 5 should still be the left operand (condition[0])
    print(f"Optimized WHERE: {optimized_where}")
    assert optimized_where[1].upper() == "AND"
    assert optimized_where[0][0].column == 'pk'
    assert optimized_where[0][1] == '='
    assert optimized_where[2][0].column == 'col_int'
    assert optimized_where[2][1] == '>'


def test_condition_reorder_or(setup_condition_table, parser, optimizer):
    """Test OR conditions are reordered (least selective first)."""
    table = setup_condition_table
    # Inequality (!=) is estimated as less selective (0.9) than equality (=) (0.1)
    query_str = f"SELECT * FROM {table} WHERE pk = 5 OR col_str != 'abc'"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    
    optimized_where = optimized['where'][1]
    # Expected: col_str != 'abc' should be the left operand (condition[0]) after optimization
    assert optimized_where[1].upper() == "OR"
    assert optimized_where[0][0].column == 'col_str' # Left part of the inequality check
    assert optimized_where[0][1] == '!='
    assert optimized_where[2][0].column == 'pk' # Right part of the equality check
    assert optimized_where[2][1] == '='

def test_condition_reorder_or_reverse_input(setup_condition_table, parser, optimizer):
    """Test OR conditions are reordered even if input order is reversed."""
    table = setup_condition_table
    # Inequality (!=) is estimated as less selective (0.9) than equality (=) (0.1)
    query_str = f"SELECT * FROM {table} WHERE col_str != 'abc' OR pk = 5" # Reversed input order
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)
    
    optimized_where = optimized['where'][1]
    # Expected: col_str != 'abc' should still be the left operand (condition[0])
    assert optimized_where[1].upper() == "OR"
    assert optimized_where[0][0].column == 'col_str'
    assert optimized_where[0][1] == '!='
    assert optimized_where[2][0].column == 'pk'
    assert optimized_where[2][1] == '='

def test_condition_reorder_nested(setup_condition_table, parser, optimizer):
    """Test nested conditions are reordered correctly."""
    table = setup_condition_table
    # Original: (pk = 1 AND col_int > 10) OR (col_str != 'abc' AND col_int < 5)
    # Expected Outer OR: (col_str != 'abc' AND col_int < 5) OR (pk = 1 AND col_int > 10)
    #   -> because OR puts less selective first. != AND < (0.9 * 0.3 = 0.27) vs = AND > (0.1 * 0.3 = 0.03). 0.27 is less selective than 0.03? Error in logic - OR puts LEAST selective first (HIGHEST selectivity value). 0.27 is > 0.03, so != AND < comes first.
    # Expected Inner ANDs:
    #   Left (original right): col_int < 5 AND col_str != 'abc' (< is 0.3, != is 0.9. So < comes first)
    #   Right (original left): pk = 1 AND col_int > 10 (= is 0.1, > is 0.3. So = comes first)
    # Final expected structure: ( (col_int < 5 AND col_str != 'abc') OR (pk = 1 AND col_int > 10) ) ? No, outer OR is based on combined selectivity.
    # Let's re-evaluate outer OR: sel(left) = 0.1 * 0.3 = 0.03. sel(right) = 0.9 * 0.3 = 0.27.
    # OR puts LEAST selective first (higher number), so right side should come first.
    # Final Structure: ( (col_str != 'abc' AND col_int < 5) OR (pk = 1 AND col_int > 10) )
    # Inner ANDs:
    #   Left side (orig right): col_int < 5 AND col_str != 'abc' (sel 0.3 < sel 0.9 -> OK)
    #   Right side (orig left): pk = 1 AND col_int > 10 (sel 0.1 < sel 0.3 -> OK)

    query_str = f"SELECT * FROM {table} WHERE (pk = 1 AND col_int > 10) OR (col_str != 'abc' AND col_int < 5)"
    parsed = parser.parse(query_str)
    optimized = optimizer.optimize(parsed)

    optimized_where = optimized['where'][1] 
    # Check outer OR
    assert optimized_where[1].upper() == "OR"
    
    # Check left side of OR (should be the original right side, internally optimized)
    left_or = optimized_where[0]
    assert left_or[1].upper() == "AND"
    assert left_or[0][0].column == 'col_int' # col_int < 5
    assert left_or[0][1] == '<'
    assert left_or[2][0].column == 'col_str' # col_str != 'abc'
    assert left_or[2][1] == '!='

    # Check right side of OR (should be the original left side, internally optimized)
    right_or = optimized_where[2]
    assert right_or[1].upper() == "AND"
    assert right_or[0][0].column == 'pk' # pk = 1
    assert right_or[0][1] == '='
    assert right_or[2][0].column == 'col_int' # col_int > 10
    assert right_or[2][1] == '>'
