# parser.py

from pyparsing import *
from catalog import Catalog, TableSchema, CatalogError, UnknownTableError, UnknownColumnError

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
        

        
        # build grammar
        self.select_stmt = self._build_select_grammar()
        
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
        return self.select_stmt.parseString(query, parseAll=True)
