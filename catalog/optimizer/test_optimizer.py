import pytest
from pyparsing import ParseResults
from optimizer import QueryOptimizer
from catalog import Catalog, TableSchema
from engine import Executor, SortMergeJoin
from storage.heap_file import HeapFile

# simple class implementations for testing
class Column:
    def __init__(self, name, data_type):
        self.name = name
        self.type = data_type

class Schema:
    def __init__(self, columns, indexes=None, primary_key=None):
        self.columns = [Column(name, dtype) for name, dtype in columns]
        self.indexes = indexes or []
        self.primary_key = primary_key
        
    def col_names(self):
        return [col.name for col in self.columns]

class Table:
    def __init__(self, table, alias=None):
        self.table = table
        self.alias = alias
        
    def copy(self):
        return Table(self.table, self.alias)

class Query:
    def __init__(self, query_type='SELECT', tables=None, columns=None, where=None):
        self.query_type = query_type
        self.tables = tables or []
        self.columns = columns or []
        self.where = where
        
    def copy(self):
        new_query = Query(self.query_type, 
                         [table.copy() for table in self.tables], 
                         self.columns.copy() if self.columns else [], 
                         self.where)
        if hasattr(self, 'join_method'):
            new_query.join_method = self.join_method
        return new_query

# fixtures
@pytest.fixture
def catalog():
    """Create a catalog with test tables"""
    catalog = Catalog() 
    
    # define schemas for test tables
    small_table_schema = Schema([
        ('id', 'INTEGER'),
        ('name', 'TEXT')
    ], indexes=['id'], primary_key='id')
    
    large_table_schema = Schema([
        ('id', 'INTEGER'),
        ('user_id', 'INTEGER'),
        ('content', 'TEXT'),
        ('created_at', 'TIMESTAMP')
    ], indexes=['id', 'user_id'], primary_key='id')
    
    # patch the get_schema method
    def get_schema(table_name):
        if table_name == 'small_table':
            return small_table_schema
        elif table_name == 'large_table':
            return large_table_schema
        else:
            raise ValueError(f"Unknown table: {table_name}")
    
    catalog.get_schema = get_schema
    return catalog

@pytest.fixture
def optimizer(catalog):
    """Create an optimizer instance with the catalog"""
    return QueryOptimizer(catalog)

@pytest.fixture
def parsed_query():
    """Create a parsed query for testing"""
    query = Query(query_type='SELECT')
    return query

# test cases
def test_optimizer_initialization(optimizer):
    """Test that the optimizer initializes correctly"""
    assert optimizer is not None
    assert optimizer.catalog is not None

def test_optimize_non_select_query(optimizer):
    """Test that non-SELECT queries are returned unmodified"""
    query = Query(query_type='INSERT')
    result = optimizer.optimize(query)
    assert result == query

def test_condition_optimization(optimizer):
    """Test that WHERE conditions are optimized correctly"""
    # create a WHERE clause with AND conditions
    where_clause = ParseResults(['WHERE',
        ParseResults(['id', '=', '5', 'AND', 'name', '!=', 'test'])
    ])
    
    tables = [Table('small_table')]
    optimized = optimizer.optimize_conditions(where_clause, tables)
    
    # the equality condition should be first (more selective)
    assert optimized[1][0] == 'id'
    assert optimized[1][1] == '='
    assert optimized[1][2] == '5'

def test_join_method_selection_small_tables(optimizer):
    """Test join method selection for small tables"""
    tables = [Table('small_table'), Table('small_table')]
    method = optimizer.select_join_method(tables)
    
    # for small tables, nested loop should be preferred
    assert method == 'nested_loop'

def test_join_method_selection_large_tables(optimizer):
    """Test join method selection for large tables"""
    tables = [Table('large_table'), Table('large_table')]
    method = optimizer.select_join_method(tables)
    
    # for large indexed tables, sort-merge might be preferred
    assert method in ['nested_loop', 'sort_merge']

def test_optimize_select_query(optimizer, parsed_query):
    """Test optimizing a SELECT query with WHERE and multiple tables"""
    # set up a query with WHERE and multiple tables
    parsed_query.query_type = 'SELECT'
    parsed_query.tables = [Table('small_table'), Table('large_table')]
    
    # add a WHERE clause
    where_clause = ParseResults(['WHERE',
        ParseResults(['small_table.id', '=', 'large_table.user_id'])
    ])
    parsed_query.where = where_clause

    optimized = optimizer.optimize(parsed_query)
    
    # check that join method was selected
    assert hasattr(optimized, 'join_method')

@pytest.mark.parametrize("table_name,expected_size", [
    ('small_table', 200),  # 2 columns * 100
    ('large_table', 400),  # 4 columns * 100
])
def test_table_size_estimation(optimizer, table_name, expected_size):
    """Test the table size estimation logic"""
    size = optimizer._estimate_table_size(table_name)
    assert size == expected_size

def test_has_index(optimizer):
    """Test the index detection logic"""
    assert optimizer._has_index('small_table') == True
    assert optimizer._has_index('large_table') == True
    assert optimizer._has_index('nonexistent_table') == False

# integration tests with executor
def test_integration_with_executor(monkeypatch, optimizer, catalog):
    """Test integration with the executor"""
    # create an executor
    executor = Executor(catalog, '/tmp')
    
    # set the optimizer
    monkeypatch.setattr(executor, "optimizer", optimizer)
    
    # create a query
    query = Query(query_type='SELECT')
    query.tables = [Table('small_table', 'a'), Table('large_table', 'b')]
    query.columns = ['*']
    
    # add a WHERE clause for the join
    where_clause = ParseResults(['WHERE',
        ParseResults(['a.id', '=', 'b.user_id'])
    ])
    query.where = where_clause
    
    # track if _build_select_plan was called with optimized query
    called_with_optimized = False
    
    def mock_build_select_plan(q):
        nonlocal called_with_optimized
        # check that the query has been optimized
        if hasattr(q, 'join_method'):
            called_with_optimized = True
        return None  # return a placeholder
    
    # patch the _build_select_plan method
    original_build_select_plan = executor._build_select_plan
    monkeypatch.setattr(executor, "_build_select_plan", mock_build_select_plan)
    
    # run the query (with exception handling as in original)
    try:
        executor.run(query)
    except Exception:
        # we expect an exception since we're using placeholders
        pass
    
    # restore the original method
    monkeypatch.setattr(executor, "_build_select_plan", original_build_select_plan)
    
    # verify the optimizer was used
    assert called_with_optimized

def test_sort_merge_join():
    """Test the SortMergeJoin operator"""
    # create data for left and right inputs
    left_data = [
        {"a.id": 1, "a.name": "Alice"},
        {"a.id": 2, "a.name": "Bob"},
        {"a.id": 3, "a.name": "Charlie"},
        {"a.id": 5, "a.name": "Eve"}
    ]
    
    right_data = [
        {"b.id": 101, "b.user_id": 1, "b.content": "Post 1"},
        {"b.id": 102, "b.user_id": 2, "b.content": "Post 2"},
        {"b.id": 103, "b.user_id": 3, "b.content": "Post 3"},
        {"b.id": 104, "b.user_id": 3, "b.content": "Post 4"},
        {"b.id": 105, "b.user_id": 4, "b.content": "Post 5"}
    ]
    
    # create simple iterator classes
    class LeftOperator:
        def __init__(self):
            self.data = left_data.copy()
            
        def open(self):
            pass
            
        def next(self):
            if not self.data:
                return None
            return self.data.pop(0)
            
        def close(self):
            pass
    
    class RightOperator:
        def __init__(self):
            self.data = right_data.copy()
            
        def open(self):
            pass
            
        def next(self):
            if not self.data:
                return None
            return self.data.pop(0)
            
        def close(self):
            pass
    
    # create the operators
    left_op = LeftOperator()
    right_op = RightOperator()
    
    # create the SortMergeJoin operator
    join_op = SortMergeJoin(left_op, right_op, "a.id", "b.user_id")
    
    # open the operator
    join_op.open()
    
    # collect the results
    results = []
    while True:
        row = join_op.next()
        if row is None:
            break
        results.append(row)
    
    # close the operator
    join_op.close()
    
    # verify the results
    assert len(results) == 4  # 1 match for Alice, 1 for Bob, 2 for Charlie
    
    # check specific joins
    assert any(r["a.name"] == "Alice" and r["b.content"] == "Post 1" for r in results)
    assert any(r["a.name"] == "Bob" and r["b.content"] == "Post 2" for r in results)
    assert any(r["a.name"] == "Charlie" and r["b.content"] == "Post 3" for r in results)
    assert any(r["a.name"] == "Charlie" and r["b.content"] == "Post 4" for r in results)
    
    # eve should not have any matches
    assert not any(r["a.name"] == "Eve" for r in results)

def test_executor_with_optimizer_integration(monkeypatch, optimizer, catalog):
    """Test the full integration of optimizer with executor"""
    # create an executor with our optimizer
    executor = Executor(catalog, '/tmp')
    monkeypatch.setattr(executor, "optimizer", optimizer)
    
    # create simple heap file classes
    class SmallHeap:
        def __init__(self):
            self.schema = Schema([('id', 'INTEGER'), ('name', 'TEXT')],
                              indexes=['id'], primary_key='id')
            self.table = 'small_table'
    
    class LargeHeap:
        def __init__(self):
            self.schema = Schema([('id', 'INTEGER'), ('user_id', 'INTEGER'),
                               ('content', 'TEXT'), ('created_at', 'TIMESTAMP')],
                              indexes=['id', 'user_id'], primary_key='id')
            self.table = 'large_table'
    
    # patch the HeapFile constructor
    def heap_file_factory(table_name):
        if table_name == 'small_table':
            return SmallHeap()
        elif table_name == 'large_table':
            return LargeHeap()
        raise ValueError(f"Unknown table: {table_name}")
    
    # monkeypatch the HeapFile instantiation
    monkeypatch.setattr(HeapFile, "__new__", lambda cls, catalog, data_dir, table_name: 
                        heap_file_factory(table_name))
    
    # create a test query
    query = Query(query_type='SELECT')
    query.tables = [Table('small_table', 'a'), Table('large_table', 'b')]
    query.columns = ['*']
    
    # add a WHERE clause for the join
    where_clause = ParseResults(['WHERE',
        ParseResults(['a.id', '=', 'b.user_id'])
    ])
    query.where = where_clause
    
    # create a mock plan that produces results
    class MockPlan:
        def __init__(self):
            self.results = [{"result": "row1"}, {"result": "row2"}, None]
            self.index = 0
            
        def open(self):
            pass
            
        def next(self):
            if self.index >= len(self.results):
                return None
            result = self.results[self.index]
            self.index += 1
            return result
            
        def close(self):
            pass
    
    # track if _build_select_plan was called with optimized query
    called_with_optimized = False
    
    def mock_build_plan(q):
        nonlocal called_with_optimized
        # check for join_method
        if hasattr(q, 'join_method'):
            called_with_optimized = True
        return MockPlan()
    
    monkeypatch.setattr(executor, "_build_select_plan", mock_build_plan)
    
    # run the query
    results, _ = executor.run(query)
    
    # verify that the optimizer was used
    assert called_with_optimized
    assert len(results) == 2  # two rows from our mock plan
