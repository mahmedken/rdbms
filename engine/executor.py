"""converts parsed sql into a physical plan and executes it"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Tuple

from catalog import Catalog, CatalogError
from storage.heap_file import HeapFile
from .operators import (
    Projection, Selection, TableScan, NestedLoopJoin, Aggregation, 
    InsertOperator, DeleteOperator, UpdateOperator, Row,
    Sort, GroupBy, Having, Limit, SortMergeJoin
)
from pyparsing import ParseResults
from optimizer import QueryOptimizer

class Executor:
    def __init__(self, catalog: Catalog, data_dir):
        self.catalog = catalog
        self.data_dir = data_dir
        self.optimizer = QueryOptimizer(catalog)

    # public api
    def run(self, parsed_query) -> tuple[List[Row], float]:
        query_type = self._get_query_type(parsed_query)
        
        if query_type == 'SELECT':
            # Apply optimization if optimizer is available
            if hasattr(self, 'optimizer'):
                optimized_query = self.optimizer.optimize(parsed_query)
                plan = self._build_select_plan(optimized_query)
            else:
                plan = self._build_select_plan(parsed_query)
        elif query_type == 'INSERT':
            plan = self._build_insert_plan(parsed_query)
        elif query_type == 'DELETE':
            plan = self._build_delete_plan(parsed_query)
        elif query_type == 'UPDATE':
            plan = self._build_update_plan(parsed_query)
        elif query_type == 'CREATE_TABLE':
            return self._execute_create_table(parsed_query)
        elif query_type == 'DROP_TABLE':
            return self._execute_drop_table(parsed_query)
        elif query_type == 'CREATE_INDEX':
            return self._execute_create_index(parsed_query)
        elif query_type == 'DROP_INDEX':
            return self._execute_drop_index(parsed_query)
        
        else:
            raise ValueError(f"Unsupported query type: {query_type}")
        
        # execute the plan
        start = time.perf_counter()
        plan.open()
        rows: List[Row] = []
        while True:
            row = plan.next()
            if row is None:
                break
            rows.append(row)
        plan.close()
        elapsed = time.perf_counter() - start
        return rows, elapsed


    def _execute_create_table(self, parsed_query) -> tuple[List[Row], float]:
        print(f"Executing CREATE TABLE for {parsed_query.table_name}")
        start = time.perf_counter()
        table_name = parsed_query.table_name.lower()
        columns = [(col_def.name.lower(), col_def.type.upper()) 
                for col_def in parsed_query.columns]
        
        # Extract primary key if specified
        primary_key = parsed_query.get('primary_key')
        
        try:
            self.catalog.create_table(table_name, columns, primary_key=primary_key)
            message = f"Table '{table_name}' created successfully"
            if primary_key:
                message += f" with primary key '{primary_key}'"
        except CatalogError as e:
            message = f"Error: {str(e)}"
        
        elapsed = time.perf_counter() - start
        return [{"message": message}], elapsed

    def _execute_drop_table(self, parsed_query) -> tuple[List[Row], float]:
        print(f"Executing DROP TABLE for {parsed_query.table_name}")
        start = time.perf_counter()
        table_name = parsed_query.table_name.lower()
        
        try:
            # get the file path before dropping the table from catalog
            table_file_path = f"{self.data_dir}/{table_name}.dat"
            
            # remove table from catalog
            self.catalog.drop_table(table_name)
            
            # delete the physical file
            import os
            if os.path.exists(table_file_path):
                os.remove(table_file_path)
                
            message = f"Table '{table_name}' dropped successfully"
        except CatalogError as e:
            message = f"Error: {str(e)}"
        
        elapsed = time.perf_counter() - start
        return [{"message": message}], elapsed


    def _execute_create_index(self, parsed_query) -> tuple[List[Row], float]:
        print(f"Executing CREATE INDEX on {parsed_query.table_name}.{parsed_query.column_name}")
        start = time.perf_counter()
        table_name = parsed_query.table_name.lower()
        column_name = parsed_query.column_name.lower()
        
        try:
            self.catalog.create_index(table_name, column_name)
            message = f"Index created on {table_name}.{column_name} successfully"
        except CatalogError as e:
            message = f"Error: {str(e)}"
        
        elapsed = time.perf_counter() - start
        return [{"message": message}], elapsed

    def _execute_drop_index(self, parsed_query) -> tuple[List[Row], float]:
        print(f"Executing DROP INDEX on {parsed_query.table_name}.{parsed_query.column_name}")
        start = time.perf_counter()
        table_name = parsed_query.table_name.lower()
        column_name = parsed_query.column_name.lower()
        
        try:
            self.catalog.drop_index(table_name, column_name)
            message = f"Index dropped on {table_name}.{column_name} successfully"
        except CatalogError as e:
            message = f"Error: {str(e)}"
        
        elapsed = time.perf_counter() - start
        return [{"message": message}], elapsed







    def _get_query_type(self, query):
        """Determine the type of SQL query"""
        if hasattr(query, 'query_type'):
            return query.query_type
        else:
            raise ValueError("Unable to determine query type")

    # plan construction for different query types
    def _build_select_plan(self, q):
        """Build a plan for SELECT queries"""
        # check if we have aggregation in the query
        has_aggregation = any(col.getName() == "aggregation" for col in q.columns if col != "*")
        has_group_by = 'group_by' in q
        
        # from clause - build base scans (handle alias)
        scans: Dict[str, TableScan] = {}
        for tbl in q.tables:
            table_name = tbl.table[0].lower() if isinstance(tbl.table, list) else tbl.table.lower()
            alias = tbl.alias if "alias" in tbl and tbl.alias else table_name
            heap = HeapFile(self.catalog, self.data_dir, table_name)
            scans[alias] = TableScan(heap, alias)
        
        # join or cross products
        plan = None
        if len(scans) == 1:
            plan = next(iter(scans.values()))
        elif len(scans) == 2:
            (a_alias, a_scan), (b_alias, b_scan) = scans.items()
            join_pred = self._compile_predicate(q.where, scans) if "where" in q else lambda r: True
            
            # Use the optimizer's join method selection if available
            join_method = q.get('join_method', 'nested_loop')
            
            if join_method == 'nested_loop':
                plan = NestedLoopJoin(a_scan, b_scan, join_pred)
            else:
                # In the future, you can implement other join methods here
                # For now, default to nested loop join
                plan = NestedLoopJoin(a_scan, b_scan, join_pred)
        else:
            raise NotImplementedError(">2 tables not supported")

        # selections (for single‑table queries)
        if len(scans) == 1 and "where" in q:
            plan = Selection(plan, self._compile_predicate(q.where, scans))





        elif len(scans) == 2:
            (a_alias, a_scan), (b_alias, b_scan) = scans.items()
            join_pred = self._compile_predicate(q.where, scans) if "where" in q else lambda r: True
            
            # Use the optimizer's join method selection if available
            join_method = q.get('join_method', 'nested_loop')
            
            if join_method == 'sort_merge':
                # For sort-merge join, we need to identify the join columns
                # This is a simplified approach - in a real system, you'd extract this from the WHERE clause
                join_cols = self._extract_join_columns(q.where, a_alias, b_alias) if "where" in q else None
                
                if join_cols:
                    left_key, right_key = join_cols
                    plan = SortMergeJoin(a_scan, b_scan, left_key, right_key)
                else:
                    # Fall back to nested loop if we can't identify join columns
                    plan = NestedLoopJoin(a_scan, b_scan, join_pred)
            else:
                # Default to nested loop join
                plan = NestedLoopJoin(a_scan, b_scan, join_pred)






        if has_group_by:
            # build GROUP BY operator with aggregations
            group_keys = self._qualify_cols(q.group_by, scans)
            
            # build aggregation functions dict: { output_col -> (func, input_col) }
            agg_functions = {}
            
            # create output column names for aggregations
            for i, col in enumerate(q.columns):
                if col.getName() == "aggregation":
                    func = col.function.upper()
                    
                    # handle COUNT(*) special case
                    if func == "COUNT" and col.argument[0] == "*":
                        output_col = f"COUNT(*)"
                        input_col = "*"
                    else:
                        # handle regular aggregation on column
                        arg = col.argument[0]
                        if arg.table:
                            # qualified column
                            tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                        else:
                            # unqualified column - infer table
                            tbl = self._infer_table(arg.column, scans)
                            
                        input_col = f"{tbl}.{arg.column}"
                        output_col = f"{func}({input_col})"
                    
                    agg_functions[output_col] = (func, input_col)
            
            plan = GroupBy(plan, group_keys, agg_functions)
            
            # Apply HAVING clause if present
            if 'having' in q:
                having_pred = self._compile_predicate(q.having, scans)
                plan = Having(plan, having_pred)
            
            # we need a projection to handle the column structure in the output
            cols = []
            for col in q.columns:
                if col == "*":
                    # can't mix * with aggregates or GROUP BY
                    continue
                elif col.getName() == "aggregation":
                    func = col.function.upper()
                    if func == "COUNT" and col.argument[0] == "*":
                        cols.append(f"COUNT(*)")
                    else:
                        arg = col.argument[0]
                        if arg.table:
                            tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                        else:
                            tbl = self._infer_table(arg.column, scans)
                        cols.append(f"{func}({tbl}.{arg.column})")
                else:
                    # regular column (must be in GROUP BY)
                    if col.table:
                        tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
                    else:
                        tbl = self._infer_table(col.column, scans)
                    cols.append(f"{tbl}.{col.column}")
            plan = Projection(plan, cols)
        elif has_aggregation:
            # Simple aggregation without GROUP BY
            agg_functions = {}
            
            # create output column names for aggregations
            for i, col in enumerate(q.columns):
                if col.getName() == "aggregation":
                    func = col.function.upper()
                    
                    # handle COUNT(*) special case
                    if func == "COUNT" and col.argument[0] == "*":
                        output_col = f"COUNT(*)"
                        input_col = "*"
                    else:
                        # handle regular aggregation on column
                        arg = col.argument[0]
                        if arg.table:
                            # qualified column
                            tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                        else:
                            # unqualified column - infer table
                            tbl = self._infer_table(arg.column, scans)
                            
                        input_col = f"{tbl}.{arg.column}"
                        output_col = f"{func}({input_col})"
                    
                    agg_functions[output_col] = (func, input_col)
                    
            plan = Aggregation(plan, agg_functions)
            
            # we need a projection to handle mixed aggregates and regular columns
            if not all(col.getName() == "aggregation" for col in q.columns if col != "*"):
                cols = []
                for col in q.columns:
                    if col == "*":
                        # can't mix * with aggregates, so skip
                        continue
                    elif col.getName() == "aggregation":
                        func = col.function.upper()
                        if func == "COUNT" and col.argument[0] == "*":
                            cols.append(f"COUNT(*)")
                        else:
                            arg = col.argument[0]
                            if arg.table:
                                tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                            else:
                                tbl = self._infer_table(arg.column, scans)
                            cols.append(f"{func}({tbl}.{arg.column})")
                    else:
                        # regular column
                        if col.table:
                            tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
                        else:
                            tbl = self._infer_table(col.column, scans)
                        cols.append(f"{tbl}.{col.column}")
                plan = Projection(plan, cols)
        else:
            # regular projection (no aggregation)
            cols = ["*"] if q.columns and q.columns[0] == "*" else self._qualify_cols(q.columns, scans)
            plan = Projection(plan, cols)
        
        # ORDER BY clause
        if 'order_by' in q:
            sort_keys = []
            for order_item in q.order_by:
                item = order_item[0]  # column reference or aggregation
                direction = order_item.direction  # ASC or DESC
                
                # Handle aggregation functions in ORDER BY
                if item.getName() == "aggregation":
                    func = item.function.upper()
                    arg = item.argument[0]
                    
                    # Handle COUNT(*) special case
                    if func == "COUNT" and arg == "*":
                        qualified_col = f"COUNT(*)"
                    else:
                        # Get table name for the column in the aggregation
                        if arg.table:
                            tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                        else:
                            tbl = self._infer_table(arg.column, scans)
                        qualified_col = f"{func}({tbl}.{arg.column})"
                else:
                    # regular column reference
                    col = item
                    if col.table:
                        tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
                    else:
                        tbl = self._infer_table(col.column, scans)
                    qualified_col = f"{tbl}.{col.column}"
                
                is_ascending = direction.upper() == "ASC"
                sort_keys.append((qualified_col, is_ascending))
            
            plan = Sort(plan, sort_keys)
            
        # LIMIT clause
        if 'limit' in q:
            limit_value = q.limit
            plan = Limit(plan, limit_value)
            
        return plan
    
    def _build_insert_plan(self, q):
        """Build a plan for INSERT queries"""
        table_name = q.table_name.lower()
        heap = HeapFile(self.catalog, self.data_dir, table_name)
        
        # Get column order - if specified in query, use that order
        if hasattr(q, 'columns') and q.columns:
            col_names = [col.lower() for col in q.columns]
            # Reorder values to match schema column order
            schema_cols = heap.schema.col_names()
            values = [None] * len(schema_cols)
            
            for i, col_name in enumerate(col_names):
                if i < len(q.insert_values):
                    schema_idx = schema_cols.index(col_name)
                    values[schema_idx] = q.insert_values[i]
        else:
            # If no columns specified, assume values are in schema order
            values = list(q.insert_values)
        
        # Create an insert operator
        return InsertOperator(heap, tuple(values))
    
    def _build_delete_plan(self, q):
        """Build a plan for DELETE queries"""
        
        table_name = q.table_name.lower()
        heap = HeapFile(self.catalog, self.data_dir, table_name)
        
        # Create a table scan
        scan = TableScan(heap, table_name)
        
        # If there's a WHERE clause, add a selection
        if "where" in q:
            selection = Selection(scan, self._compile_predicate(q.where, None))
            plan = DeleteOperator(selection, heap)
        else:
            # Delete all rows
            plan = DeleteOperator(scan, heap)
            
        return plan
    
    def _build_update_plan(self, q):
        """Build a plan for UPDATE queries"""
        table_name = q.table_name.lower()
        heap = HeapFile(self.catalog, self.data_dir, table_name)
        
        # Create a table scan
        scan = TableScan(heap, table_name)
        
        # Extract the column updates
        updates = {}
        for assignment in q.assignments:
            col_name = assignment.column.lower()
            value = assignment.value
            updates[col_name] = value
        
        # If there's a WHERE clause, add a selection
        if "where" in q:
            selection = Selection(scan, self._compile_predicate(q.where, None))
            plan = UpdateOperator(selection, heap, updates)
        else:
            # Update all rows
            plan = UpdateOperator(scan, heap, updates)
            
        return plan

    # helpers
    def _qualify_cols(self, columns, scans):
        qualified = []
        for col in columns:
            # skip aggregation functions - they're handled separately
            if col.getName() == "aggregation":
                continue
                
            # extract table name/alias properly
            if col.table:
                tbl = col.table[0].lower() if isinstance(col.table, ParseResults) else col.table.lower()
            else:
                tbl = self._infer_table(col.column, scans)
                
            qualified.append(f"{tbl}.{col.column}")
        return qualified

    def _infer_table(self, col, scans):
        for alias, scan in scans.items():
            if col.lower() in scan.heap.schema.col_names():
                return alias
        raise ValueError(f"Ambiguous column {col}")

    def _compile_predicate(self, where_clause, scans) -> Callable[[Row], bool]:
        # recursively turn parse tree into python lambda
        # where_clause is a nested list (pyparsing output)
        
        # extract the actual condition from WHERE clause if needed
        if isinstance(where_clause, ParseResults) and len(where_clause) >= 2 and where_clause[0] == 'WHERE' or where_clause[0] == 'HAVING':
            condition = where_clause[1]  # skip the 'WHERE' keyword
        else:
            condition = where_clause
        
        # helper function to extract value from row or literal
        def _value(expr, row):
            if isinstance(expr, (int, str)):
                return expr
                
            # Handle aggregate function expressions
            if isinstance(expr, ParseResults) and len(expr) >= 2:
                # Check if it looks like an aggregate function
                if expr[0] in ("MIN", "MAX", "SUM", "AVG", "COUNT"):
                    func = expr[0].upper()
                    arg = expr[1]

                    if func == "COUNT" and arg == "*":
                        agg_key = "COUNT(*)"
                    else:
                        # For column-based aggregates
                        if hasattr(arg, 'table') and hasattr(arg, 'column'):
                            col = arg.column
                            if arg.table:
                                tbl = arg.table[0].lower() if isinstance(arg.table, ParseResults) else arg.table.lower()
                                col_name = f"{tbl}.{col}"
                            elif self._infer_table(col, scans):
                                tbl = self._infer_table(col, scans)
                                col_name = f"{tbl}.{col}"
                            else:
                                # For unqualified columns, try to find in the row
                                for key in row:
                                    if key.endswith(f".{col}") or (f"{col}" in key):
                                        col_name = key
                                        break
                                else:
                                    raise ValueError(f"Column not found for aggregate: {col}")
                            
                            agg_key = f"{func}({col_name})"
                        else:
                            raise ValueError(f"Invalid aggregate argument: {arg}")
                    if agg_key in row:
                        return row[agg_key]
                    raise ValueError(f"Aggregate function not found in result: {agg_key}")
            
            # Handle column references
            if hasattr(expr, 'table') and hasattr(expr, 'column'):
                if expr.table:
                    # extract table/alias name properly
                    table = expr.table[0].lower() if isinstance(expr.table, ParseResults) else expr.table.lower()
                    col_name = f"{table}.{expr.column}"
                else:
                    # find unqualified column in row
                    for key in row:
                        if key.endswith(f".{expr.column}"):
                            return row[key]
                    raise ValueError(f"Column not found: {expr.column}")
                return row.get(col_name)
                
            raise ValueError(f"Unsupported expression type: {type(expr)}")
        
        # map ops to lambda functions
        comparison_ops = {
            "=": lambda l, r: l == r,
            "!=": lambda l, r: l != r,
            "<": lambda l, r: l < r,
            ">": lambda l, r: l > r,
            "<=": lambda l, r: l <= r,
            ">=": lambda l, r: l >= r
        }
        
        def _eval(node):
            # handle comparison operators
            if isinstance(node, ParseResults) and len(node) == 3 and node[1] in comparison_ops:
                left, op, right = node
                op_func = comparison_ops[op]
                return lambda row: op_func(_value(left, row), _value(right, row))

            # handle logical operators
            if isinstance(node, ParseResults) and len(node) >= 3 and node[1] in ("AND", "and", "OR", "or"):
                left, op, right = node
                lfn = _eval(left)
                rfn = _eval(right)
                if op.upper() == "AND":
                    return lambda row: lfn(row) and rfn(row)
                elif op.upper() == "OR":
                    return lambda row: lfn(row) or rfn(row)
                
            # if node is already a function
            if callable(node):
                return node
                
            raise ValueError(f"Unable to evaluate node: {node}")

        try:
            return _eval(condition)
        except Exception as e:
            raise RuntimeError(f"Failed to compile predicate: {e}") from e



    def _extract_join_columns(self, where_clause, left_alias, right_alias):
        """Extract join columns from WHERE clause for sort-merge join"""
        # Extract the condition from WHERE clause if needed
        if isinstance(where_clause, ParseResults) and len(where_clause) >= 2 and where_clause[0] == 'WHERE':
            condition = where_clause[1]
        else:
            condition = where_clause
        
        # Look for equality conditions between columns from different tables
        if isinstance(condition, ParseResults) and len(condition) == 3 and condition[1] == '=':
            left, op, right = condition
            
            # Check if these are column references
            if (hasattr(left, 'table') and hasattr(left, 'column') and 
                hasattr(right, 'table') and hasattr(right, 'column')):
                
                left_table = left.table[0].lower() if isinstance(left.table, ParseResults) else left.table.lower()
                right_table = right.table[0].lower() if isinstance(right.table, ParseResults) else right.table.lower()
                
                # If columns are from our two tables
                if (left_table == left_alias and right_table == right_alias):
                    return (f"{left_table}.{left.column}", f"{right_table}.{right.column}")
                elif (left_table == right_alias and right_table == left_alias):
                    return (f"{right_table}.{right.column}", f"{left_table}.{left.column}")
        
        # For AND conditions, try both sides
        if isinstance(condition, ParseResults) and len(condition) == 3 and condition[1].upper() == "AND":
            left_result = self._extract_join_columns(condition[0], left_alias, right_alias)
            if left_result:
                return left_result
            
            right_result = self._extract_join_columns(condition[2], left_alias, right_alias)
            if right_result:
                return right_result
        
        return None
