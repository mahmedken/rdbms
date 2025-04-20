# parser.py

from pyparsing import *
from catalog import Catalog, TableSchema, CatalogError, UnknownTableError, UnknownColumnError, Column, IndexError_

class SQLParser:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

        # identifiers and literals
        self.identifier = Word(alphas, alphanums + '_')
        self.quoted_str = QuotedString("'")
        self.integer = Word(nums).setParseAction(lambda t: int(t[0]))

        self.column_ref = Group(
            Optional(self.identifier + Suppress('.'))("table") +
            self.identifier("column")
        )
        
        # basic tokens
        self.LPAR, self.RPAR, self.COMMA = map(Suppress, "(),")
        self.STAR = Literal('*')
        
        # SQL keywords
        self.SELECT = CaselessKeyword("SELECT")
        self.FROM = CaselessKeyword("FROM")
        self.WHERE = CaselessKeyword("WHERE")
        
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
        
        # data types
        self.INT = CaselessKeyword("INT")
        self.STR = CaselessKeyword("STR")
        self.datatype = (
            self.INT("type") |
            self.STR("type") 
        )
        
        # literals for values
        self.value = (
            self.quoted_str |
            self.integer
        )
        
        # build grammar
        self.select_stmt = self._build_select_grammar()
        self.create_table_stmt = self._build_create_table_grammar()
        self.drop_table_stmt = self._build_drop_table_grammar()
        self.create_index_stmt = self._build_create_index_grammar()
        self.drop_index_stmt = self._build_drop_index_grammar()
        
        # DML statement grammar
        self.insert_stmt = self._build_insert_grammar()
        self.update_stmt = self._build_update_grammar()
        self.delete_stmt = self._build_delete_grammar()
        
        # complete SQL statement grammar
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
    
    def _build_select_grammar(self):
        column_ref = self.column_ref
        
        # add Group() around table_ref
        table_ref = Group(
            self.identifier("table") + 
            Optional(Suppress("AS") + self.identifier("alias"))
        )
        
        condition = self._build_condition_grammar()
        
        return (self.SELECT + delimitedList(column_ref | self.STAR)("columns") +
                self.FROM + delimitedList(table_ref)("tables") +
                Optional(self.WHERE + condition)("where")).setParseAction(self._validate_query)
    
    def _build_condition_grammar(self):
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
    
    def _build_create_table_grammar(self):
        # column definition: name datatype
        column_def = Group(
            self.identifier("name") + 
            self.datatype
        )
        
        # column list: (col1 type1, col2 type2, ...)
        column_list = self.LPAR + delimitedList(column_def)("columns") + self.RPAR
        
        # CREATE TABLE table_name (col1 type1, col2 type2, ...)
        return (
            self.CREATE + self.TABLE + 
            self.identifier("table_name") + 
            column_list
        ).setParseAction(self._handle_create_table)
    
    def _build_drop_table_grammar(self):
        # DROP TABLE table_name
        return (
            self.DROP + self.TABLE + 
            self.identifier("table_name")
        ).setParseAction(self._handle_drop_table)
    
    def _build_create_index_grammar(self):
        # CREATE INDEX table_name column_name
        return (
            self.CREATE + self.INDEX + 
            self.identifier("table_name") + 
            self.identifier("column_name")
        ).setParseAction(self._handle_create_index)
    
    def _build_drop_index_grammar(self):
        # DROP INDEX table_name column_name
        return (
            self.DROP + self.INDEX + 
            self.identifier("table_name") + 
            self.identifier("column_name")
        ).setParseAction(self._handle_drop_index)
    
    def _build_insert_grammar(self):
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
        ).setParseAction(self._handle_insert)
    
    def _build_update_grammar(self):
        # SET clause: col1 = val1, col2 = val2, ...
        assignment = Group(
            self.identifier("column") + 
            Suppress("=") + 
            self.value("value")
        )
        
        set_clause = delimitedList(assignment)("assignments")
        
        # WHERE clause (optional)
        condition = self._build_condition_grammar()
        
        # UPDATE table_name SET col1 = val1, col2 = val2 [WHERE condition]
        return (
            self.UPDATE + 
            self.identifier("table_name") +
            self.SET + set_clause +
            Optional(self.WHERE + condition)("where")
        ).setParseAction(self._handle_update)
    
    def _build_delete_grammar(self):
        # WHERE clause (optional)
        condition = self._build_condition_grammar()
        
        # DELETE FROM table_name [WHERE condition]
        return (
            self.DELETE + self.FROM +
            self.identifier("table_name") +
            Optional(self.WHERE + condition)("where")
        ).setParseAction(self._handle_delete)
    
    def _handle_create_table(self, parse_result):
        table_name = parse_result.table_name.lower()
        columns = []
        
        # process column definitions
        for col_def in parse_result.columns:
            col_name = col_def.name.lower()
            col_type = col_def.type.upper()
                
            columns.append((col_name, col_type))
        
        # create table in catalog
        try:
            self.catalog.create_table(table_name, columns)
            return f"Table '{table_name}' created successfully"
        except CatalogError as e:
            raise ParseException(str(e))
    
    def _handle_drop_table(self, parse_result):
        table_name = parse_result.table_name.lower()
        
        try:
            self.catalog.drop_table(table_name)
            return f"Table '{table_name}' dropped successfully"
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _handle_create_index(self, parse_result):
        table_name = parse_result.table_name.lower()
        column_name = parse_result.column_name.lower()
        
        try:
            self.catalog.create_index(table_name, column_name)
            return f"Index created on {table_name}.{column_name}"
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
        except UnknownColumnError:
            raise ParseException(f"Unknown column: {column_name}")
        except IndexError_ as e:
            raise ParseException(str(e))
    
    def _handle_drop_index(self, parse_result):
        table_name = parse_result.table_name.lower()
        column_name = parse_result.column_name.lower()
        
        try:
            self.catalog.drop_index(table_name, column_name)
            return f"Index dropped on {table_name}.{column_name}"
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
        except IndexError_ as e:
            raise ParseException(str(e))

    def _handle_insert(self, parse_result):
        table_name = parse_result.table_name.lower()
        
        try:
            # Get table schema
            schema = self.catalog.get_schema(table_name)
            
            # Validate columns if specified, otherwise use all table columns
            if "columns" in parse_result:
                columns = [col.lower() for col in parse_result.columns]
                # Check if all columns exist in the table
                for col in columns:
                    if col not in schema.col_names():
                        raise ParseException(f"Unknown column: {col}")
            else:
                columns = schema.col_names()
                
            # Check if values count matches column count
            if len(parse_result.insert_values) != len(columns):
                raise ParseException(f"Column count ({len(columns)}) does not match value count ({len(parse_result.values)})")
            
            # Validate value types
            for i, value in enumerate(parse_result.insert_values):
                col_name = columns[i]
                col_type = next(col.type for col in schema.columns if col.name.lower() == col_name)
                
                # Check type compatibility
                if (col_type == 'INT' and not isinstance(value, int)) or \
                   (col_type == 'STR' and not isinstance(value, str)):
                    raise ParseException(f"Type mismatch for column '{col_name}': expected {col_type}")
            
            # In a real implementation, this would insert data into storage
            return f"Inserted 1 row into table '{table_name}'"
            
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _handle_update(self, parse_result):
        table_name = parse_result.table_name.lower()
        
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
                col_type = next(col.type for col in schema.columns if col.name.lower() == col_name)
                if (col_type == 'INT' and not isinstance(value, int)) or \
                   (col_type == 'STR' and not isinstance(value, str)):
                    raise ParseException(f"Type mismatch for column '{col_name}': expected {col_type}")
            
            # Validate WHERE clause if present
            if 'where' in parse_result:
                self._validate_condition(parse_result.where, table_name)
            
            # In a real implementation, this would update data in storage
            return f"Updated rows in table '{table_name}'"
            
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _handle_delete(self, parse_result):
        table_name = parse_result.table_name.lower()
        
        try:
            # Check if table exists
            self.catalog.get_schema(table_name)
            
            # Validate WHERE clause if present
            if 'where' in parse_result:
                self._validate_condition(parse_result.where, table_name)
            
            # In a real implementation, this would delete data from storage
            if 'where' in parse_result:
                return f"Deleted rows from table '{table_name}'"
            else:
                return f"Deleted all rows from table '{table_name}'"
                
        except UnknownTableError:
            raise ParseException(f"Unknown table: {table_name}")
    
    def _validate_condition(self, condition, table_name):
        """Helper method to validate conditions in WHERE clauses for a single table"""
        schema = self.catalog.get_schema(table_name)
        
        # Recursively check all parts of the condition
        def validate_expr(expr):
            if isinstance(expr, ParseResults):
                if len(expr) == 3 and expr[1] in ('=', '!=', '<', '>', '<=', '>='):
                    # This is a simple comparison
                    left = expr[0]
                    right = expr[2]
                    left_type = self._get_operand_type(left, schema)
                    right_type = self._get_operand_type(right, schema)
                    
                    if left_type != right_type:
                        raise ParseException(f"Type mismatch in condition: {left} ({left_type}) vs {right} ({right_type})")
                else:
                    # This is a complex condition (AND/OR)
                    for item in expr:
                        validate_expr(item)
        
        validate_expr(condition)
    
    def _get_operand_type(self, operand, schema):
        """Determine the type of an operand in a condition"""
        if isinstance(operand, int):
            return 'INT'
        elif isinstance(operand, str):
            return 'STR'
        elif isinstance(operand, ParseResults):
            # This is a column reference
            col_name = operand.column.lower()
            
            # Check if column exists in the schema
            if col_name not in schema.col_names():
                raise ParseException(f"Unknown column: {col_name}")
                
            # Get column type from schema
            return next(col.type for col in schema.columns if col.name.lower() == col_name)
        
        return None
    
    def _validate_query(self, parse_result):
        # validate tables with proper ParseResults access
        for table in parse_result.tables:
            try:
                # access table name correctly from grouped results
                table_name = table.table[0].lower() if isinstance(table.table, ParseResults) else table.table.lower()
                self.catalog.get_schema(table_name)
            except UnknownTableError:
                raise ParseException(f"Unknown table: {table_name}")

        # validate ALL columns in SELECT clause, not just qualified ones
        for col in parse_result.columns:
            if col == '*':  # skip validation for wildcard
                continue
                
            if col.table:  # qualified column
                # extract table name from ParseResults
                table_name = col.table[0].lower()  # access the first element 
                schema = self.catalog.get_schema(table_name)
                
                if col.column.lower() not in schema.col_names():
                    raise ParseException(f"Unknown column {table_name}.{col.column}")
            else:  # unqualified column
                # check if this column exists in any of the referenced tables
                found = False
                for table in parse_result.tables:
                    table_name = table.table[0].lower() if isinstance(table.table, ParseResults) else table.table.lower()
                    schema = self.catalog.get_schema(table_name)
                    if col.column.lower() in schema.col_names():
                        found = True
                        break
                        
                if not found:
                    raise ParseException(f"Unknown column: {col.column}")
                    
        # validate WHERE clause types
        if 'where' in parse_result:
            for cond in parse_result.where:
                left_type = self._get_type(cond[0], parse_result.tables)
                right_type = self._get_type(cond[2], parse_result.tables)
                
                if left_type != right_type:
                    raise ParseException(
                        f"Type mismatch: {cond[0]} ({left_type}) vs {cond[2]} ({right_type})"
                    )
                    
        return parse_result

    def _get_type(self, element, tables):
        if isinstance(element, (int, str)):
            return 'INT' if isinstance(element, int) else 'STR'
            
        #handle column references
        if element.table:
            schema = self.catalog.get_schema(element.table.lower())
            return next(c.type for c in schema.columns 
                       if c.name.lower() == element.column.lower())
                       
        # unqualified column -- find table
        for table in tables:
            schema = self.catalog.get_schema(table.table.lower())
            if element.column.lower() in schema.col_names():
                return next(c.type for c in schema.columns 
                           if c.name.lower() == element.column.lower())
                           
        raise UnknownColumnError(element.column)

    def parse(self, query):
        return self.stmt.parseString(query, parseAll=True)
