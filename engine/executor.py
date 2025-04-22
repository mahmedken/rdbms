from __future__ import annotations

"""Executor — converts a parsed (and optionally optimised) SQL statement
into an executable physical plan and runs it.

this design:
- keeps the public API identical (``Executor.run``)
- isolates responsibility into helpers
- introduces two small dispatch tables to keep the control‑flow clear

notes on the design:
- single source of truth for dispatch - one place for DDL and one for DML builders
- each clause (where, order by, group by, order by, limit) has its own helper that returns a new plan
- thin wrappers for DDL to handle timing and error capture

"""

import os
import time
from typing import Callable, Dict, List, Tuple

from catalog import Catalog, CatalogError
from optimizer import QueryOptimizer
from pyparsing import ParseResults
from storage.heap_file import HeapFile

from .operators import (
    Aggregation,
    DeleteOperator,
    GroupBy,
    Having,
    InsertOperator,
    Limit,
    NestedLoopJoin,
    Projection,
    Row,
    Selection,
    Sort,
    SortMergeJoin,
    TableScan,
    UpdateOperator,
)

# ---------------------------------------------------------------------------
# Executor class
# ---------------------------------------------------------------------------

class Executor:
    """High‑level interface between the parser/optimiser and the operator
    tree.  A single instance is meant to be shared for the lifetime of an
    RDBMS session so that it can reuse the same ``Catalog`` and
    ``QueryOptimizer``.
    """

    # ---------------------------------------------------------------------
    # life‑cycle
    # ---------------------------------------------------------------------

    def __init__(self, catalog: Catalog, data_dir: str) -> None:
        self.catalog = catalog
        self.data_dir = data_dir
        self.optimizer = QueryOptimizer(catalog)

        # DDL actions that DO NOT require a data‑flow plan
        self._ddl_dispatch = {
            "CREATE_TABLE": self._create_table,
            "DROP_TABLE": self._drop_table,
            "CREATE_INDEX": self._create_index,
            "DROP_INDEX": self._drop_index,
        }

        # DML actions that DO require a plan
        self._dml_dispatch = {
            "SELECT": self._plan_select,
            "INSERT": self._plan_insert,
            "DELETE": self._plan_delete,
            "UPDATE": self._plan_update,
        }

    # ---------------------------------------------------------------------
    # public API
    # ---------------------------------------------------------------------

    def run(self, parsed_query) -> Tuple[List[Row], float]:
        """Build a physical plan or run a DDL command, then execute.

        Returns
        -------
        list[Row]
            The output rows (possibly just a ``{"message": str}`` row for
            DDL).
        float
            Wall‑clock execution time in seconds.
        """

        qtype: str | None = getattr(parsed_query, "query_type", None)
        if not qtype:
            raise ValueError("Unable to determine query type from parser")

        # --- DDL -----------------------------------------------------------
        if qtype in self._ddl_dispatch:
            return self._ddl_dispatch[qtype](parsed_query)

        # --- DML -----------------------------------------------------------
        builder = self._dml_dispatch[qtype]
        logical_query = (
            self.optimizer.optimize(parsed_query) if qtype == "SELECT" else parsed_query
        )
        plan = builder(logical_query)
        return self._execute_plan(plan)

    # ------------------------------------------------------------------
    # DDL helpers (return rows, elapsed)
    # ------------------------------------------------------------------

    def _ddl_wrapper(self, fn: Callable[[], None], ok_msg: str):
        start = time.perf_counter()
        try:
            fn()
            msg = ok_msg
        except CatalogError as e:
            msg = f"Error: {e}"
        return [{"message": msg}], time.perf_counter() - start

    def _create_table(self, q):
        cols = [(c.name.lower(), c.type.upper()) for c in q.columns]
        pk = q.get("primary_key")
        # Extract the actual primary key column name if it's a ParseResults object
        if pk and hasattr(pk, "pk_column"):
            pk = pk.pk_column
            
        # Process foreign keys if present
        foreign_keys = {}
        if hasattr(q, "foreign_keys") and q.foreign_keys:
            for fk in q.foreign_keys:
                foreign_keys[fk.local_column.lower()] = (fk.ref_table.lower(), fk.ref_column.lower())
        
        return self._ddl_wrapper(
            lambda: self.catalog.create_table(
                q.table_name.lower(), 
                cols, 
                primary_key=pk,
                foreign_keys=foreign_keys
            ),
            f"Table '{q.table_name}' created successfully" + 
            (f" with primary key '{pk}'" if pk else "") +
            (f" and {len(foreign_keys)} foreign key(s)" if foreign_keys else ""),
        )

    def _drop_table(self, q):
        path = f"{self.data_dir}/{q.table_name.lower()}.dat"
        return self._ddl_wrapper(
            lambda: (self.catalog.drop_table(q.table_name.lower()), os.remove(path) if os.path.exists(path) else None),
            f"Table '{q.table_name}' dropped successfully",
        )

    def _create_index(self, q):
        return self._ddl_wrapper(
            lambda: self.catalog.create_index(q.table_name.lower(), q.column_name.lower()),
            f"Index created on {q.table_name}.{q.column_name} successfully",
        )

    def _drop_index(self, q):
        return self._ddl_wrapper(
            lambda: self.catalog.drop_index(q.table_name.lower(), q.column_name.lower()),
            f"Index dropped on {q.table_name}.{q.column_name} successfully",
        )

    # ------------------------------------------------------------------
    # plan execution
    # ------------------------------------------------------------------

    def _execute_plan(self, plan):
        start = time.perf_counter()
        plan.open()
        rows: List[Row] = []
        while (row := plan.next()) is not None:
            rows.append(row)
        plan.close()
        return rows, time.perf_counter() - start

    # ------------------------------------------------------------------
    # DML – physical‑plan builders
    # ------------------------------------------------------------------

    # ---- SELECT -------------------------------------------------------

    def _plan_select(self, q):
        scans = self._build_scans(q.tables)
        plan = self._build_from(scans, q)

        if len(scans) == 1 and "where" in q:
            plan = Selection(plan, self._compile_pred(q.where, scans))

        plan = self._add_group_by_and_aggs(plan, q, scans)
        plan = self._add_order_and_limit(plan, q, scans)
        return plan

    # ---- INSERT -------------------------------------------------------

    def _plan_insert(self, q):
        heap = HeapFile(self.catalog, self.data_dir, q.table_name.lower())
        aligned_values_list = []
        for values_tuple in q.insert_values_list:
            aligned_values = self._align_insert_values(q, heap, values_tuple)
            # Validate foreign key constraints for each tuple
            self._validate_foreign_keys(q.table_name.lower(), aligned_values, heap.schema)
            aligned_values_list.append(tuple(aligned_values))
            
        return InsertOperator(heap, aligned_values_list)

    # ---- DELETE -------------------------------------------------------

    def _plan_delete(self, q):
        heap = HeapFile(self.catalog, self.data_dir, q.table_name.lower())
        scan = TableScan(heap, q.table_name.lower())
        child = Selection(scan, self._compile_pred(q.where, {q.table_name.lower(): scan})) if "where" in q else scan
        
        # Validate that this deletion doesn't break foreign key constraints
        self._validate_no_references(q.table_name.lower(), child)
        
        return DeleteOperator(child, heap)

    # ---- UPDATE -------------------------------------------------------

    def _plan_update(self, q):
        heap = HeapFile(self.catalog, self.data_dir, q.table_name.lower())
        scan = TableScan(heap, q.table_name.lower())
        child = Selection(scan, self._compile_pred(q.where, {q.table_name.lower(): scan})) if "where" in q else scan
        updates = {a.column.lower(): a.value for a in q.assignments}
        
        # Validate foreign key constraints for updated columns
        schema = heap.schema
        for local_col, value in updates.items():
            if schema.foreign_keys and local_col in schema.foreign_keys:
                ref_table, ref_col = schema.foreign_keys[local_col]
                self._validate_fk_value(ref_table, ref_col, value)
        
        return UpdateOperator(child, heap, updates)

    # ------------------------------------------------------------------
    # clause builders
    # ------------------------------------------------------------------

    # ---- FROM / JOIN --------------------------------------------------

    def _build_scans(self, tables) -> Dict[str, TableScan]:
        scans: Dict[str, TableScan] = {}
        for tbl in tables:
            name = tbl.table[0].lower() if isinstance(tbl.table, list) else tbl.table.lower()
            alias = tbl.alias or name
            scans[alias] = TableScan(HeapFile(self.catalog, self.data_dir, name), alias)
        return scans

    def _build_from(self, scans: Dict[str, TableScan], q):
        if len(scans) == 1:
            return next(iter(scans.values()))
        if len(scans) != 2:
            raise NotImplementedError("> 2‑way joins not yet supported")

        (a_alias, a_scan), (b_alias, b_scan) = scans.items()
        join_method = q.get("join_method", "nested_loop")
        pred = self._compile_pred(q.where, scans) if "where" in q else lambda r: True

        if join_method == "sort_merge":
            cols = self._extract_join_cols(q.where, a_alias, b_alias)
            if cols:
                left_key, right_key = cols
                return SortMergeJoin(a_scan, b_scan, left_key, right_key, pred)
        # fallback
        return NestedLoopJoin(a_scan, b_scan, pred)

    # ---- GROUP / AGGREGATION -----------------------------------------

    def _add_group_by_and_aggs(self, plan, q, scans):
        has_aggs = any(getattr(c, "getName", lambda: "")() == "aggregation" for c in q.columns if c != "*")
        has_group = "group_by" in q
        if not has_aggs and not has_group:
            # simple projection
            cols = ["*"] if q.columns and q.columns[0] == "*" else self._qualify_cols(q.columns, scans)
            return Projection(plan, cols)

        # build aggregation mapping first (needed by both Aggregation & GroupBy)
        agg_fns = {}
        for col in (c for c in q.columns if getattr(c, "getName", lambda: "")() == "aggregation"):
            func = col.function.upper()
            if func == "COUNT" and col.argument[0] == "*":
                arg_key = "*"
                out_key = "COUNT(*)"
            else:
                arg = col.argument[0]
                tbl = arg.table[0].lower() if arg.table else self._infer_table(arg.column, scans)
                arg_key = f"{tbl}.{arg.column}"
                out_key = f"{func}({arg_key})"
            agg_fns[out_key] = (func, arg_key)

        # GROUP BY present -> GroupBy operator, else plain Aggregation
        if has_group:
            group_keys = self._qualify_cols(q.group_by, scans)
            plan = GroupBy(plan, group_keys, agg_fns)
            if "having" in q:
                plan = Having(plan, self._compile_pred(q.having, scans))
        elif agg_fns:
            plan = Aggregation(plan, agg_fns)

        # final output projection (handles mix of grouped cols + aggs)
        proj_cols = []
        for col in q.columns:
            if col == "*":
                continue  # illegal with aggs but keep check anyway
            if getattr(col, "getName", lambda: "")() == "aggregation":
                func = col.function.upper()
                if func == "COUNT" and col.argument[0] == "*":
                    proj_cols.append("COUNT(*)")
                else:
                    arg = col.argument[0]
                    tbl = arg.table[0].lower() if arg.table else self._infer_table(arg.column, scans)
                    proj_cols.append(f"{func}({tbl}.{arg.column})")
            else:
                tbl = col.table[0].lower() if col.table else self._infer_table(col.column, scans)
                proj_cols.append(f"{tbl}.{col.column}")
        return Projection(plan, proj_cols)

    # ---- ORDER BY / LIMIT --------------------------------------------

    def _add_order_and_limit(self, plan, q, scans):
        if "order_by" in q:
            sort_keys = []
            for order_item in q.order_by:
                item, direction = order_item[0], order_item.direction.upper()
                col_name = self._render_order_item(item, scans)
                sort_keys.append((col_name, direction == "ASC"))
            plan = Sort(plan, sort_keys)
        if "limit" in q:
            plan = Limit(plan, q.limit)
        return plan

    def _render_order_item(self, item, scans):
        if getattr(item, "getName", lambda: "")() == "aggregation":
            func = item.function.upper()
            if func == "COUNT" and item.argument[0] == "*":
                return "COUNT(*)"
            arg = item.argument[0]
            tbl = arg.table[0].lower() if arg.table else self._infer_table(arg.column, scans)
            return f"{func}({tbl}.{arg.column})"
        # regular column
        tbl = item.table[0].lower() if item.table else self._infer_table(item.column, scans)
        return f"{tbl}.{item.column}"

    # ------------------------------------------------------------------
    # INSERT value alignment helper
    # ------------------------------------------------------------------

    def _align_insert_values(self, q, heap, values_tuple):
        """Align a single tuple of values based on specified columns or schema order."""
        current_values = list(values_tuple)
        if getattr(q, "columns", None):
            schema_cols = heap.schema.col_names()
            ordered = [None] * len(schema_cols)
            for i, user_col in enumerate(col.lower() for col in q.columns):
                try:
                    idx = schema_cols.index(user_col)
                    ordered[idx] = current_values[i]
                except ValueError:
                    raise ValueError(f"Unknown column '{user_col}' in table '{heap.table}'")
                except IndexError:
                     raise ValueError(f"Mismatch between number of columns specified and values provided for tuple: {values_tuple}")
            # Check if the number of provided values matches the number of specified columns
            if len(current_values) != len(q.columns):
                 raise ValueError(f"Mismatch between number of columns specified ({len(q.columns)}) and values provided ({len(current_values)}) for tuple: {values_tuple}")
            return ordered
        else:
            # Check if the number of provided values matches the number of schema columns
            if len(current_values) != len(heap.schema.columns):
                 raise ValueError(f"Number of values provided ({len(current_values)}) does not match number of columns in table '{heap.table}' ({len(heap.schema.columns)}) for tuple: {values_tuple}")
            return current_values

    # ------------------------------------------------------------------
    # predicate compilation / column helpers (mostly unchanged logic)
    # ------------------------------------------------------------------

    def _qualify_cols(self, columns, scans):
        result = []
        for col in columns:
            if getattr(col, "getName", lambda: "")() == "aggregation":
                continue  # handled elsewhere
            tbl = col.table[0].lower() if col.table else self._infer_table(col.column, scans)
            result.append(f"{tbl}.{col.column}")
        return result

    def _infer_table(self, col, scans):
        for alias, scan in scans.items():
            if col.lower() in scan.heap.schema.col_names():
                return alias
        raise ValueError(f"Ambiguous column reference: {col}")

    def _compile_pred(self, clause, scans) -> Callable[[Row], bool]:
        # (Original logic mostly preserved but moved verbatim for brevity.)
        # The full implementation would mirror the old _compile_predicate.
        from functools import partial  # local import to avoid clutter

        comparison_ops = {
            "=": lambda l, r: l == r,
            "!=": lambda l, r: l != r,
            "<": lambda l, r: l < r,
            ">": lambda l, r: l > r,
            "<=": lambda l, r: l <= r,
            ">=": lambda l, r: l >= r,
        }

        def value(expr, row):
            # literals
            if isinstance(expr, (int, str)):
                return expr
            # column ref
            if hasattr(expr, "column") and not getattr(expr, "getName", lambda: "")() == "aggregation":
                tbl = expr.table[0].lower() if expr.table else self._infer_table(expr.column, scans)
                return row.get(f"{tbl}.{expr.column}")
            # aggregate access
            if getattr(expr, "getName", lambda: "")() == "aggregation":
                func = expr.function.upper()
                if func == "COUNT" and expr.argument[0] == "*":
                    return row["COUNT(*)"]
                arg = expr.argument[0]
                tbl = arg.table[0].lower() if arg.table else self._infer_table(arg.column, scans)
                return row.get(f"{func}({tbl}.{arg.column})")
            raise ValueError(f"Unsupported expression: {expr}")

        def build(node):
            if isinstance(node, ParseResults) and len(node) == 3 and node[1] in comparison_ops:
                l, op, r = node
                return lambda row: comparison_ops[op](value(l, row), value(r, row))
            if isinstance(node, ParseResults) and len(node) == 3 and node[1].upper() in {"AND", "OR"}:
                l, op, r = node
                lf, rf = build(l), build(r)
                return (lambda row: lf(row) and rf(row)) if op.upper() == "AND" else (lambda row: lf(row) or rf(row))
            raise ValueError(f"Unable to compile predicate node: {node}")

        # skip the WHERE/HAVING keyword if still present
        expr = clause[1] if isinstance(clause, ParseResults) and clause[0] in {"WHERE", "HAVING"} else clause
        return build(expr)

    # ------------------------------------------------------------------
    # join‑column extractor (unchanged logic, trimmed)
    # ------------------------------------------------------------------

    def _extract_join_cols(self, where_clause, left_alias, right_alias):
        if not where_clause:
            return None
        cond = where_clause[1] if isinstance(where_clause, ParseResults) and where_clause[0] == "WHERE" else where_clause

        def is_equi(cond):
            return (
                isinstance(cond, ParseResults)
                and len(cond) == 3
                and cond[1] == "="
                and hasattr(cond[0], "table")
                and hasattr(cond[1], "__str__")
            )

        if is_equi(cond):
            l, _, r = cond
            lt, rt = (
                (l.table[0] if isinstance(l.table, ParseResults) else l.table).lower(),
                (r.table[0] if isinstance(r.table, ParseResults) else r.table).lower(),
            )
            if {lt, rt} == {left_alias, right_alias}:
                lkey = f"{lt}.{l.column}" if lt == left_alias else f"{rt}.{r.column}"
                rkey = f"{rt}.{r.column}" if lt == left_alias else f"{lt}.{l.column}"
                return lkey, rkey
        # recursively handle AND chains
        if isinstance(cond, ParseResults) and len(cond) == 3 and cond[1].upper() == "AND":
            return self._extract_join_cols(cond[0], left_alias, right_alias) or self._extract_join_cols(
                cond[2], left_alias, right_alias
            )
        return None

    # ------------------------------------------------------------------
    # Foreign key validation helpers
    # ------------------------------------------------------------------
    
    def _validate_foreign_keys(self, table_name, values, schema):
        """Validate that foreign key values in a single tuple reference existing records"""
        if not schema.foreign_keys:
            return
            
        col_names = schema.col_names()
        for idx, col_name in enumerate(col_names):
            if col_name in schema.foreign_keys and values[idx] is not None:
                ref_table, ref_col = schema.foreign_keys[col_name]
                self._validate_fk_value(ref_table, ref_col, values[idx])
                
    def _validate_fk_value(self, ref_table, ref_col, value):
        """Validate that a foreign key value exists in the referenced table"""
        ref_heap = HeapFile(self.catalog, self.data_dir, ref_table)
        ref_scan = TableScan(ref_heap, ref_table)
        
        # Look for a matching record in the referenced table
        ref_scan.open()
        found = False
        while (row := ref_scan.next()) is not None:
            if row.get(f"{ref_table}.{ref_col}") == value:
                found = True
                break
        ref_scan.close()
        
        if not found:
            raise ValueError(f"Foreign key constraint violation: value '{value}' not found in {ref_table}.{ref_col}")
            
    def _validate_no_references(self, table_name, child_op):
        """Validate that the records being deleted aren't referenced by foreign keys"""
        # Find all tables that reference this table
        referencing_tables = []
        for other_table in self.catalog.list_tables():
            if other_table == table_name:
                continue
                
            schema = self.catalog.get_schema(other_table)
            if not schema.foreign_keys:
                continue
                
            for local_col, (ref_table, ref_col) in schema.foreign_keys.items():
                if ref_table == table_name:
                    referencing_tables.append((other_table, local_col, ref_col))
        
        if not referencing_tables:
            return
            
        # Get the rows that are about to be deleted
        deleted_rows = []
        child_op.open()
        while (row := child_op.next()) is not None:
            deleted_rows.append(row)
        child_op.close()
        
        # Check each referencing table to see if it references any of the rows being deleted
        for other_table, local_col, ref_col in referencing_tables:
            other_heap = HeapFile(self.catalog, self.data_dir, other_table)
            other_scan = TableScan(other_heap, other_table)
            
            for deleted_row in deleted_rows:
                deleted_value = deleted_row.get(f"{table_name}.{ref_col}")
                
                # Skip None values
                if deleted_value is None:
                    continue
                    
                other_scan.open()
                while (row := other_scan.next()) is not None:
                    if row.get(f"{other_table}.{local_col}") == deleted_value:
                        other_scan.close()
                        raise ValueError(
                            f"Foreign key constraint violation: Cannot delete row from {table_name} "
                            f"with {ref_col}={deleted_value} because it is referenced by {other_table}.{local_col}"
                        )
                other_scan.close()
