# parser.py

from pyparsing import *
from pyparsing import ParseResults
from catalog import Catalog, TableSchema, CatalogError, UnknownTableError, UnknownColumnError, IndexError_

class SQLParser:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        
        # define tokens, keywords, and grammar components
        self._init_tokens()
        self._init_keywords()
        self._init_data_types()
        self._init_expressions()
        
        # build grammar for various SQL statements
        self._init_statement_grammar()
        
    def _init_tokens(self):
        """Initialize basic tokens and identifiers"""
        # Identifiers and literals
        self.identifier = Word(alphas, alphanums + '_')
        self.quoted_str = QuotedString("'")
        self.integer = Word(nums).setParseAction(lambda t: int(t[0]))

        # basix syntax tokens
        self.LPAR, self.RPAR, self.COMMA = map(Suppress, "(),")
        self.STAR = Literal('*')
        
        # value literals for INSERT/UPDATE
        self.value = self.quoted_str | self.integer
        
    def _init_keywords(self):
        """Initialize SQL keywords for different statement types"""
        # query keywords
        self.SELECT = CaselessKeyword("SELECT")
        self.FROM = CaselessKeyword("FROM")
        self.WHERE = CaselessKeyword("WHERE")
        self.DISTINCT = CaselessKeyword("DISTINCT")
        self.ORDER = CaselessKeyword("ORDER")
        self.BY = CaselessKeyword("BY")
        self.GROUP = CaselessKeyword("GROUP")
        self.HAVING = CaselessKeyword("HAVING")
        self.LIMIT = CaselessKeyword("LIMIT")
        self.ASC = CaselessKeyword("ASC")
        self.DESC = CaselessKeyword("DESC")

        # DML keywords
        self.INSERT = CaselessKeyword("INSERT")
        self.INTO = CaselessKeyword("INTO")
        self.VALUES = CaselessKeyword("VALUES")
        self.UPDATE = CaselessKeyword("UPDATE")
        self.SET = CaselessKeyword("SET")
        self.DELETE = CaselessKeyword("DELETE")
        
        # DDL keywords
        self.CREATE = CaselessKeyword("CREATE")
        self.DROP = CaselessKeyword("DROP")
        self.TABLE = CaselessKeyword("TABLE")
        self.INDEX = CaselessKeyword("INDEX")
        self.ON = CaselessKeyword("ON")
        
    def _init_data_types(self):
        """Initialize data type definitions"""
        self.INT = CaselessKeyword("INT")
        self.STR = CaselessKeyword("STR")
        self.datatype = (
            self.INT("type") |
            self.STR("type") 
        )
        
    def _init_expressions(self):
        """Initialize expression grammars for columns, aggregations, etc."""
        # Standard column reference
        self.column_ref = Group(
            Optional(self.identifier + Suppress('.'))("table") + 
            self.identifier("column")
        )
        
        # Aggregation functions
        self.agg_functions = oneOf("MIN MAX SUM AVG COUNT", caseless=True)
        
        # Aggregation expression like COUNT(*) or SUM(column)
        self.agg_expr = Group(
            self.agg_functions("function") +
            Suppress('(') +
            (self.STAR | self.column_ref)("argument") +
            Suppress(')')
        )("aggregation")
        
    def _init_statement_grammar(self):
        """Initialize grammar for all SQL statement types"""
        # Query statements
        self.select_stmt = self._build_select_grammar()
        
        # DDL statements
        self.create_table_stmt = self._build_create_table_grammar()
        self.drop_table_stmt = self._build_drop_table_grammar()
        self.create_index_stmt = self._build_create_index_grammar()
        self.drop_index_stmt = self._build_drop_index_grammar()
        
        # DML statements
        self.insert_stmt = self._build_insert_grammar()
        self.update_stmt = self._build_update_grammar()
        self.delete_stmt = self._build_delete_grammar()
        
        # Complete SQL statement grammar
        self.stmt = (
            self.select_stmt | 
            self.create_table_stmt | 
            self.drop_table_stmt | 
            self.create_index_stmt | 
            self.drop_index_stmt |
            self.insert_stmt |
            self.update_stmt |
            self.delete_stmt
        )
        
    def _build_having_condition_grammar(self):
        """Build grammar for HAVING conditions that supports aggregation functions"""
        expr = Forward()
        comp_op = oneOf("= != < > <= >=")
        
        # allow aggregation expressions in HAVING conditions
        agg_expr = self.agg_expr
        
        # atoms can be literals, columns, or aggregation expressions
        #atom = self.quoted_str | self.integer | self.column_ref | agg_expr
        # match am aggregate first - a hack that took me forever to figure out
        atom = agg_expr | self.column_ref | self.quoted_str | self.integer

        condition = Group(atom + comp_op + atom)
        
        expr <<= infixNotation(
            condition,
            [
                (CaselessKeyword("AND"), 2, OpAssoc.LEFT),
                (CaselessKeyword("OR"), 2, OpAssoc.LEFT),
            ]
        )
        return expr
    
    
    def _build_condition_grammar(self):
        """Build grammar for WHERE conditions"""
        expr = Forward()
        comp_op = oneOf("= != < > <= >=")
        atom = self.quoted_str | self.integer | self.column_ref
        condition = Group(atom + comp_op + atom)
        
        expr <<= infixNotation(
            condition,
            [
                (CaselessKeyword("AND"), 2, OpAssoc.LEFT),
                (CaselessKeyword("OR"), 2, OpAssoc.LEFT),
            ]
        )
        return expr
    

    def _build_select_grammar(self):
        """Build grammar for SELECT statements"""
        # Select item can be an aggregate or a column reference or star
        select_item = self.agg_expr | self.column_ref | self.STAR
        
        # Table reference with optional alias
        table_ref = Group(
            self.identifier("table") + 
            Optional(Suppress("AS") + self.identifier("alias"))
        )
        
        # Where condition
        condition = self._build_condition_grammar()
        
        # Having condition - use specialized grammar that supports aggregates
        having_condition = self._build_having_condition_grammar()
        
        # Order by clause
        order_direction = Optional(self.ASC | self.DESC, default="ASC")("direction")
        # Allow aggregates in ORDER BY clause
        order_item = Group((self.agg_expr | self.column_ref) + order_direction)
        order_by_clause = self.ORDER + self.BY + delimitedList(order_item)("order_by")
        
        # Group by clause
        group_by_item = self.column_ref
        group_by_clause = self.GROUP + self.BY + delimitedList(group_by_item)("group_by")
        
        # Having clause (with aggregate support)
        having_clause = Optional(self.HAVING + having_condition)("having")
        
        # Limit clause
        limit_clause = self.LIMIT + self.integer("limit")
        
        return (self.SELECT + Optional(self.DISTINCT("distinct")) + delimitedList(select_item)("columns") +
                self.FROM + delimitedList(table_ref)("tables") +
                Optional(self.WHERE + condition)("where") +
                Optional(group_by_clause) +
                having_clause +
                Optional(order_by_clause) +
                Optional(limit_clause)).setParseAction(self._validate_select)

    def _build_create_table_grammar(self):
        """Build grammar for CREATE TABLE statements"""
        # Column definition: name datatype
        column_def = Group(
            self.identifier("name") + 
            self.datatype
        )
        
        # Column list: (col1 type1, col2 type2, ...)
        column_list = self.LPAR + delimitedList(column_def)("columns") + self.RPAR
        
        # CREATE TABLE table_name (col1 type1, col2 type2, ...)
        return (
            self.CREATE + self.TABLE + 
            self.identifier("table_name") + 
            column_list
        ).setParseAction(self._validate_create_table)
    
    def _build_drop_table_grammar(self):
        """Build grammar for DROP TABLE statements"""
        return (
            self.DROP + self.TABLE + 
            self.identifier("table_name")
        ).setParseAction(self._validate_drop_table)
    
    def _build_create_index_grammar(self):
        """Build grammar for CREATE INDEX statements"""
        return (
            self.CREATE + self.INDEX + 
            self.identifier("table_name") + 
            self.identifier("column_name")
        ).setParseAction(self._validate_create_index)
    
    def _build_drop_index_grammar(self):
        """Build grammar for DROP INDEX statements"""
        return (
            self.DROP + self.INDEX + 
            self.identifier("table_name") + 
            self.identifier("column_name")
        ).setParseAction(self._validate_drop_index)
    
    def _build_insert_grammar(self):
        """Build grammar for INSERT statements"""
        # Values list: ('value1', 123, ...)
        values_list = self.LPAR + delimitedList(self.value)("insert_values") + self.RPAR
        
        # Column list (optional): (col1, col2, ...)
        column_list = self.LPAR + delimitedList(self.identifier)("columns") + self.RPAR
        
        # INSERT INTO table_name [(col1, col2, ...)] VALUES ('val1', 123, ...)
        return (
            self.INSERT + self.INTO +
            self.identifier("table_name") +
            Optional(column_list) +
            self.VALUES + values_list
        ).setParseAction(self._validate_insert)
    
    def _build_update_grammar(self):
        """Build grammar for UPDATE statements"""
        # SET clause: col1 = val1, col2 = val2, ...
        assignment = Group(
            self.identifier("column") + 
            Suppress("=") + 
            self.value("value")
        )
        
        set_clause = delimitedList(assignment)("assignments")
        
        # WHERE clause 
        condition = self._build_condition_grammar()
        
        # UPDATE table_name SET col1 = val1, col2 = val2 [WHERE condition]
        return (
            self.UPDATE + 
            self.identifier("table_name") +
            self.SET + set_clause +
            Optional(self.WHERE + condition)("where")
        ).setParseAction(self._validate_update)
    
    def _build_delete_grammar(self):
        """Build grammar for DELETE statements"""
        # WHERE clause (optional)
        condition = self._build_condition_grammar()
        
        # DELETE FROM table_name [WHERE condition]
        return (
            self.DELETE + self.FROM +
            self.identifier("table_name") +
            Optional(self.WHERE + condition)("where")
        ).setParseAction(self._validate_delete)



      
        

    def _validate_create_table(self, parse_result):
        """Validate CREATE TABLE statements without execution"""
        table_name = parse_result.table_name.lower()
        
        # validate that the table doesn't already exist
        try:
            self.catalog.get_schema(table_name)
            raise ParseException(f"Cannot create table '{table_name}': table already exists")
        except UnknownTableError:
            # this is expected - we want the table to not exist yet
            pass
        
        # validate column definitions
        columns = []
        column_names = set()
        
        for col_def in parse_result.columns:
            col_name = col_def.name.lower()
            col_type = col_def.type.upper()
            
            # check for duplicate column names
            if col_name in column_names:
                raise ParseException(f"Duplicate column name '{col_name}' in CREATE TABLE statement")
            
            column_names.add(col_name)
            
            # validate column type
            if col_type not in ["INT", "STR"]:
                raise ParseException(f"Invalid data type '{col_type}' for column '{col_name}'")
            
            columns.append((col_name, col_type))
        
        # ensure at least one column is defined
        if not columns:
            raise ParseException("CREATE TABLE must define at least one column")
        
        parse_result['query_type'] = 'CREATE_TABLE'
        return parse_result

    





    def _validate_drop_table(self, parse_result):
        """Validate DROP TABLE statements"""
        table_name = parse_result.table_name.lower()
        
        # validate that the table exists in the catalog
        try:
            self.catalog.get_schema(table_name)
        except UnknownTableError:
            raise ParseException(f"Cannot drop table '{table_name}': table does not exist")
        
        parse_result['query_type'] = 'DROP_TABLE'
        return parse_result

    
    def _validate_create_index(self, parse_result):
        """Validate CREATE INDEX statements"""
        table_name = parse_result.table_name.lower()
        column_name = parse_result.column_name.lower()
        
        # validate that the table exists
        try:
            schema = self.catalog.get_schema(table_name)
            
            # validate that the column exists in the table
            if column_name not in schema.col_names():
                raise ParseException(f"Cannot create index: column '{column_name}' does not exist in table '{table_name}'")
            
            # validate that an index doesn't already exist on this column
            try:
                self.catalog.get_index(table_name, column_name)
                raise ParseException(f"Cannot create index: index already exists on column '{column_name}' in table '{table_name}'")
            except IndexError_:
                # this is expected - we want the index to not exist yet
                pass
                
        except UnknownTableError:
            raise ParseException(f"Cannot create index: table '{table_name}' does not exist")
        
        parse_result['query_type'] = 'CREATE_INDEX'
        return parse_result


    
    def _validate_drop_index(self, parse_result):
        """Validate DROP INDEX statements"""
        table_name = parse_result.table_name.lower()
        column_name = parse_result.column_name.lower()
        
        # validate that the table exists
        try:
            schema = self.catalog.get_schema(table_name)
            
            # validate that the column exists in the table
            if column_name not in schema.col_names():
                raise ParseException(f"Cannot drop index: column '{column_name}' does not exist in table '{table_name}'")
            
            # validate that the index exists
            try:
                self.catalog.get_index(table_name, column_name)
            except IndexError_:
                raise ParseException(f"Cannot drop index: no index exists on column '{column_name}' in table '{table_name}'")
                
        except UnknownTableError:
            raise ParseException(f"Cannot drop index: table '{table_name}' does not exist")
        
        parse_result['query_type'] = 'DROP_INDEX'
        return parse_result


    def _validate_insert(self, parse_result):
        """Validate INSERT statements"""
        table_name = parse_result.table_name.lower()
        
        try:
            # Get table schema
            schema = self.catalog.get_schema(table_name)
            
            # Validate columns if specified, otherwise use all table columns
            if "columns" in parse_result:
                columns = [col.lower() for col in parse_result.columns]
                self._validate_columns_exist(columns, schema)
            else:
                columns = schema.col_names()
                
            # Check if values count matches column count
            if len(parse_result.insert_values) != len(columns):
                raise ParseException(f"Column count ({len(columns)}) does not match value count ({len(parse_result.insert_values)})")
            
            # Validate value types
            for i, value in enumerate(parse_result.insert_values):
                col_name = columns[i]
                col_type = self._get_column_type(col_name, schema)
                
                # Check type compatibility
                self._validate_value_type(value, col_type, col_name)
            
            # Add query type identifier
            parse_result['query_type'] = 'INSERT'
            
            # Return the parsed query object after validation
            return parse_result
            
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _validate_update(self, parse_result):
        """Validate UPDATE statements"""
        table_name = parse_result.table_name.lower()
        alias_map = {table_name: table_name}
        
        try:
            # Get table schema
            schema = self.catalog.get_schema(table_name)
            
            # Validate columns in assignments
            for assignment in parse_result.assignments:
                col_name = assignment.column.lower()
                value = assignment.value
                
                # Check if column exists
                if col_name not in schema.col_names():
                    raise ParseException(f"Unknown column: {col_name}")
                
                # Check type compatibility
                col_type = self._get_column_type(col_name, schema)
                self._validate_value_type(value, col_type, col_name)
            
            # Validate WHERE clause if present
            if 'where' in parse_result:
                condition = self._extract_condition(parse_result.where)
                self._validate_where_condition(condition, table_name, alias_map)
            
            # Add query type identifier
            parse_result['query_type'] = 'UPDATE'
            
            # Return the parsed query object after validation
            return parse_result
            
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _validate_delete(self, parse_result):
        """Validate DELETE statements"""
        table_name = parse_result.table_name.lower()
        alias_map = {table_name: table_name}

        try:
            # Check if table exists
            self.catalog.get_schema(table_name)
            
            # Validate WHERE clause if present
            if 'where' in parse_result:
                condition = self._extract_condition(parse_result.where)
                self._validate_where_condition(condition, table_name, alias_map)
            
            parse_result['query_type'] = 'DELETE'
            
            # Return the parsed query object after validation
            return parse_result
                
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")

    def _validate_select(self, parse_result):
        """Validate SELECT query structure and semantics"""
        # Build table alias map
        alias_map = self._build_alias_map(parse_result.tables)
        # Validate tables exist in catalog
        self._validate_tables_exist(parse_result.tables)

        # Validate columns in SELECT clause
        self._validate_select_columns(parse_result.columns, alias_map, parse_result.tables)
                    
        # Validate WHERE clause if present
        if 'where' in parse_result:
            condition = self._extract_condition(parse_result.where)
            self._validate_where_condition(condition, parse_result.tables, alias_map)
        
        # Validate GROUP BY clause if present
        if 'group_by' in parse_result:
            self._validate_group_by_columns(parse_result.group_by, alias_map)
            
            # Validate that non-aggregated columns in SELECT are in GROUP BY
            self._validate_select_with_group_by(parse_result.columns, parse_result.group_by)
            
        # Validate HAVING clause if present
        if 'having' in parse_result:
            if 'group_by' not in parse_result:
                raise ParseException("HAVING clause requires a GROUP BY clause")
            self._validate_having_condition(parse_result.having, parse_result.tables, alias_map)
            
        # Validate ORDER BY clause if present
        if 'order_by' in parse_result:
            self._validate_order_by_columns(parse_result.order_by, parse_result.tables, alias_map)
            
        # Validate LIMIT if present
        if 'limit' in parse_result:
            if not isinstance(parse_result.limit, int) or parse_result.limit < 0:
                raise ParseException("LIMIT value must be a non-negative integer")
        
        parse_result['query_type'] = 'SELECT'
                    
        return parse_result
    
    def _build_alias_map(self, tables):
        """Build a map of table aliases to actual table names"""
        alias_map = {}
        for table in tables:
            table_name = table.table[0].lower() if isinstance(table.table, ParseResults) else table.table.lower()
            # store alias -> actual table name mapping
            if "alias" in table:
                alias_map[table.alias.lower()] = table_name
            else: # table name is its own alias
                alias_map[table_name] = table_name
        return alias_map
    
    def _validate_tables_exist(self, tables):
        """Validate that all referenced tables exist in the catalog"""
        for table in tables:
            try:
                # Access table name correctly from grouped results
                table_name = table.table[0].lower() if isinstance(table.table, ParseResults) else table.table.lower()
                self.catalog.get_schema(table_name)
            except UnknownTableError:
                raise ParseException(f"Unknown table: {table_name}")
    
    def _validate_select_columns(self, columns, alias_map, tables):
        """Validate columns in SELECT clause"""
        for col in columns:
            if col == '*':  # Skip validation for wildcard
                continue
                
            # Validate aggregation expressions
            if col.getName() == "aggregation":
                self._validate_aggregation(col, alias_map, tables)
                continue
                
            # Regular column validation
            self._validate_column_reference(col, alias_map)
    
    def _validate_aggregation(self, agg_expr, alias_map, tables):
        """Validate an aggregation expression"""
        func = agg_expr.function.upper()
        arg = agg_expr.argument
        
        # unpack a ParseResults object if that's what arg is
        if isinstance(arg, ParseResults) and len(arg) > 0:
            arg = arg[0]
        
        # Special case for COUNT(*)
        if func == "COUNT" and arg == "*":
            return
            
        # Skip validation for string arguments like "*"
        if isinstance(arg, str):
            return
            
        # Validate the column exists
        if arg.table:  # qualified column
            self._validate_qualified_column(arg, alias_map)
        else:  # unqualified column
            self._validate_unqualified_column(arg, alias_map)
        
        # Check if the aggregation function is appropriate for the column type
        if func in ("SUM", "AVG"):
            col_type = self._get_type(arg, tables, alias_map)
            if col_type != "INT":
                raise ParseException(f"{func} can only be applied to numeric columns, not {col_type}")
    
    def _validate_column_reference(self, col, alias_map):
        """Validate a column reference (qualified or unqualified)"""
        if col.table:  # qualified column
            self._validate_qualified_column(col, alias_map)
        else:  # unqualified column
            self._validate_unqualified_column(col, alias_map)
    
    def _validate_qualified_column(self, col, alias_map):
        """Validate a qualified column reference (table.column)"""
        alias = col.table[0].lower()
        if alias not in alias_map:
            raise ParseException(f"Unknown table alias: {alias}")
            
        table_name = alias_map[alias]
        schema = self.catalog.get_schema(table_name)
        
        if col.column.lower() not in schema.col_names():
            raise ParseException(f"Unknown column {alias}.{col.column}")
    
    def _validate_unqualified_column(self, col, alias_map):
        """Validate an unqualified column reference"""
        found = False
        for table_name in alias_map.values():
            schema = self.catalog.get_schema(table_name)
            if col.column.lower() in schema.col_names():
                found = True
                break
                
        if not found:
            raise ParseException(f"Unknown column: {col.column}")
    
    def _extract_condition(self, where_clause):
        """Extract the condition part from a WHERE clause"""
        if isinstance(where_clause, ParseResults) and len(where_clause) > 1 and where_clause[0] == 'WHERE':
            return where_clause[1]
        return where_clause
    
    def _validate_where_condition(self, expr, tables, alias_map):
        """Validate a WHERE condition for correct types and columns"""
        # Skip if we can't parse the expression structure
        if not isinstance(expr, ParseResults) or len(expr) < 3:
            return
            
        # Single clause (comparison)
        if expr[1] in ("=", "!=", "<", ">", "<=", ">="):
            left_type = self._get_type(expr[0], tables, alias_map)
            right_type = self._get_type(expr[2], tables, alias_map)
            if left_type != right_type:
                raise ParseException(f"Type mismatch: {expr[0]} ({left_type}) vs {expr[2]} ({right_type})")
        # Compound clause (AND/OR)
        elif expr[1].upper() in ("AND", "OR"):
            self._validate_where_condition(expr[0], tables, alias_map)
            self._validate_where_condition(expr[2], tables, alias_map)

    def _get_type(self, element, tables, alias_map=None):
        """Get the data type of an element in an expression"""
        # Handle literals
        if isinstance(element, (int, str)):
            return 'INT' if isinstance(element, int) else 'STR'
            
        # Handle column references
        if element.table:
            return self._get_qualified_column_type(element, alias_map)
        
        # Handle single table references (UPDATE/DELETE)
        if isinstance(tables, str):
            return self._get_column_type_in_table(element.column.lower(), tables)
                       
        # Handle unqualified columns in multi-table queries
        return self._get_unqualified_column_type(element, tables)
    
    def _get_qualified_column_type(self, col_ref, alias_map):
        """Get the type of a qualified column (table.column)"""
        alias = col_ref.table[0].lower() if isinstance(col_ref.table, ParseResults) else col_ref.table.lower()
        
        if alias_map and alias in alias_map:
            table_name = alias_map[alias]
        else:
            table_name = alias
            
        return self._get_column_type_in_table(col_ref.column.lower(), table_name)
    
    def _get_unqualified_column_type(self, col_ref, tables):
        """Get the type of an unqualified column across multiple tables"""
        for table in tables:
            table_name = table.table[0].lower() if isinstance(table.table, ParseResults) else table.table.lower()
            schema = self.catalog.get_schema(table_name)
            col_name = col_ref.column.lower()
            
            if col_name in schema.col_names():
                return self._get_column_type(col_name, schema)
        raise UnknownColumnError(col_ref.column)
    
    def _get_column_type_in_table(self, col_name, table_name):
        """Get the type of a column in a specific table"""
        schema = self.catalog.get_schema(table_name)
        return self._get_column_type(col_name, schema)
    
    def _get_column_type(self, col_name, schema):
        """Get the type of a column from a schema"""
        return next(c.type for c in schema.columns if c.name.lower() == col_name)
    
    def _validate_columns_exist(self, columns, schema):
        """Validate that all columns exist in the given schema"""
        for col in columns:
            if col not in schema.col_names():
                raise ParseException(f"Unknown column: {col}")
    
    def _validate_value_type(self, value, expected_type, col_name):
        """Validate that a value matches the expected column type"""
        if (expected_type == 'INT' and not isinstance(value, int)) or \
           (expected_type == 'STR' and not isinstance(value, str)):
            raise ParseException(f"Type mismatch for column '{col_name}': expected {expected_type}")

    def _validate_group_by_columns(self, group_by_cols, alias_map):
        """Validate columns in GROUP BY clause"""
        for col in group_by_cols:
            self._validate_column_reference(col, alias_map)
            
    def _validate_select_with_group_by(self, select_cols, group_by_cols):
        """Validate that non-aggregated columns in SELECT are in GROUP BY"""
        group_by_col_names = []
        
        # Extract the qualified column names from GROUP BY
        for col in group_by_cols:
            if col.table:
                # Extract table/alias name properly
                tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
                col_name = f"{tbl}.{col.column.lower()}"
            else:
                col_name = col.column.lower()
            group_by_col_names.append(col_name)
        
        # Check each column in SELECT
        for col in select_cols:
            if col == '*':
                raise ParseException("Cannot use * with GROUP BY")
                
            if col.getName() != "aggregation":
                if col.table:
                    # Extract table/alias name properly
                    tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
                    col_name = f"{tbl}.{col.column.lower()}"
                else:
                    col_name = col.column.lower()
                    
                # Check if non-aggregated column is in GROUP BY
                if col_name not in group_by_col_names:
                    raise ParseException(f"Column '{col_name}' must be in GROUP BY clause or be an aggregate function")
    
    def _validate_having_condition(self, having_clause, tables, alias_map):
        """Validate HAVING condition (must include aggregates)"""
        # Skip the HAVING keyword if present
        if having_clause and len(having_clause) > 0:
            # The condition is directly under the 'having' key since we're using Optional() with a name
            condition = having_clause
            
            # Validate the condition (similar to WHERE but we allow aggregate functions)
            self._validate_aggregate_condition(condition, tables, alias_map)
    
    def _validate_aggregate_condition(self, expr, tables, alias_map):
        """Validate a condition that may contain aggregate functions"""
        # Skip if we can't parse the expression structure
        if not isinstance(expr, ParseResults) or len(expr) < 3:
            return
            
        # Handle comparison operations
        if expr[1] in ("=", "!=", "<", ">", "<=", ">="):
            # Left and right operands could be columns, literals, or aggregates
            self._validate_operand(expr[0], tables, alias_map)
            self._validate_operand(expr[2], tables, alias_map)
            
        # Handle AND/OR
        elif expr[1].upper() in ("AND", "OR"):
            self._validate_aggregate_condition(expr[0], tables, alias_map)
            self._validate_aggregate_condition(expr[2], tables, alias_map)
    
    def _validate_operand(self, operand, tables, alias_map):
        """Validate an operand in a HAVING condition, which can be a column, literal, or aggregate"""
        # If it's a simple literal, nothing to validate
        if isinstance(operand, (int, str)):
            return
            
        # If it's a column reference
        if hasattr(operand, 'table') and hasattr(operand, 'column'):
            self._validate_column_reference(operand, alias_map)
            return
            
        # If it's an aggregate function like COUNT(*)
        if len(operand) >= 3 and operand[0] in ("MIN", "MAX", "SUM", "AVG", "COUNT"):
            func = operand[0].upper()
            arg = operand[1]  # This could be a column or "*"
            
            # Handle COUNT(*)
            if func == "COUNT" and arg == "*":
                return
                
            # For aggregate on column, validate the column
            if hasattr(arg, 'table') and hasattr(arg, 'column'):
                self._validate_column_reference(arg, alias_map)
                
                # Check if numeric aggregation is on numeric column
                if func in ("SUM", "AVG"):
                    col_type = self._get_type(arg, tables, alias_map)
                    if col_type != "INT":
                        raise ParseException(f"{func} can only be applied to numeric columns, not {col_type}")
                return
            
        # If we get here, it's an unsupported expression type
        raise ParseException(f"Unsupported expression in HAVING clause: {operand}")
    
    def _validate_order_by_columns(self, order_by_cols, tables, alias_map):
        """Validate columns in ORDER BY clause"""
        for order_item in order_by_cols:
            item = order_item[0]  # first element is the column reference or aggregation
            
            # Check if it's an aggregation expression
            if item.getName() == "aggregation":
                self._validate_aggregation(item, alias_map, tables)
            else:
                # Regular column validation
                self._validate_column_reference(item, alias_map)

    def parse(self, query):
        """Parse a SQL query string into a parse result object"""
        try:
            result = self.stmt.parseString(query, parseAll=True)
            return result
        except Exception as e:
            # If the general parser fails, try the specific statement parsers
            query_upper = query.upper()
            
            if query_upper.startswith("SELECT"):
                return self.select_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("INSERT"):
                return self.insert_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("UPDATE"):
                return self.update_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("DELETE"):
                return self.delete_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("CREATE TABLE"):
                return self.create_table_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("DROP TABLE"):
                return self.drop_table_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("CREATE INDEX"):
                return self.create_index_stmt.parseString(query, parseAll=True)
            elif query_upper.startswith("DROP INDEX"):
                return self.drop_index_stmt.parseString(query, parseAll=True)
            else:
                raise
