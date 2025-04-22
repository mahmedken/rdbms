from __future__ import annotations

from pyparsing import ParseException, ParseResults
from catalog import Catalog, UnknownTableError, IndexError_  

class QueryValidator:  
    def __init__(self, catalog: Catalog):
        self.cat = catalog
        # dispatch table
        self._rules = {
            "SELECT": self._select,
            "INSERT": self._insert,
            "UPDATE": self._update,
            "DELETE": self._delete,
            "CREATE_TABLE": self._create_table,
            "DROP_TABLE": self._drop_table,
            "CREATE_INDEX": self._create_index,
            "DROP_INDEX": self._drop_index,
        }

    # ------------------------------------------------ public -------------
    def validate(self, q: ParseResults) -> None:
        qtype = q["query_type"]
        self._rules[qtype](q)

    # ------------------------------------------------ helpers ------------
    def _schema(self, name: str):
        return self.cat.get_schema(name.lower())

    def _col_type(self, schema, col):
        return next(c.type for c in schema.columns if c.name.lower() == col.lower())

    def _alias_map(self, tables):
        m = {}
        for t in tables:
            name = (t.table[0] if isinstance(t.table, ParseResults) else t.table).lower()
            m[(t.alias or name).lower()] = name
        return m

    # ------------------------------------------------ statement‑specific --
    def _select(self, q):
        amap = self._alias_map(q.tables)
        for tbl in amap.values():
            try:
                self._schema(tbl)  # raises if unknown
            except UnknownTableError:
                raise ParseException(f"unknown table {tbl}")
        def _check_col(col):
            if col == "*":
                return
            if col.getName() == "aggregation":
                arg = col.argument[0]
                if arg == "*":
                    return
                _check_col(arg)
                return
            tbl = (col.table[0] if col.table else None)
            if tbl:
                if tbl.lower() not in amap:
                    raise ParseException(f"unknown table alias {tbl}")
                if col.column.lower() not in self._schema(amap[tbl.lower()]).col_names():
                    raise ParseException(f"unknown column {tbl}.{col.column}")
            else:
                found = sum(col.column.lower() in self._schema(t).col_names() for t in amap.values())
                if found != 1:
                    raise ParseException(f"ambiguous column {col.column}")
        for c in q.columns:
            _check_col(c)
        if "group_by" in q:
            # Check all columns in GROUP BY
            for c in q.group_by:
                _check_col(c)
            
            # Check that non-aggregated columns in SELECT are in GROUP BY
            group_by_cols = set(c.column.lower() for c in q.group_by)
            for c in q.columns:
                if c == "*":
                    raise ParseException("cannot use * with GROUP BY")
                if c.getName() != "aggregation":
                    col_name = c.column.lower()
                    if col_name not in group_by_cols:
                        raise ParseException(f"column {c.column} in SELECT must be in GROUP BY")
        if "order_by" in q:
            for itm in q.order_by:
                _check_col(itm[0])

    def _insert(self, q):
        sch = self._schema(q.table_name)
        cols = [c.lower() for c in (q.columns or sch.col_names())]
        if len(cols) != len(q.insert_values):
            raise ParseException("column/value count mismatch")
        for c in cols:
            if c not in sch.col_names():
                raise ParseException(f"unknown column {c}")

    def _update(self, q):
        sch = self._schema(q.table_name)
        for a in q.assignments:
            if a.column.lower() not in sch.col_names():
                raise ParseException(f"unknown column {a.column}")

    def _delete(self, q):
        try:
            self._schema(q.table_name)
        except UnknownTableError:
            raise ParseException(f"unknown table {q.table_name}")

    def _create_table(self, q):
        name = q.table_name.lower()
        try:
            self._schema(name)
            raise ParseException("table already exists")
        except UnknownTableError:
            pass
        cols = [c.name.lower() for c in q.columns]
        if len(cols) != len(set(cols)):
            raise ParseException("duplicate column")
        if "primary_key" in q and q.primary_key.pk_column.lower() not in cols:
            raise ParseException("primary key column not found")

    def _drop_table(self, q):
        try:
            self._schema(q.table_name)
        except UnknownTableError:
            raise ParseException(f"unknown table {q.table_name}")

    def _create_index(self, q):
        try:
            sch = self._schema(q.table_name)
        except UnknownTableError:
            raise ParseException(f"unknown table {q.table_name}")
        if q.column_name.lower() not in sch.col_names():
            raise ParseException("column does not exist")
        try:
            self.cat.get_index(q.table_name.lower(), q.column_name.lower())
            raise ParseException("index already exists")
        except IndexError_:
            pass

    def _drop_index(self, q):
        sch = self._schema(q.table_name)
        if q.column_name.lower() not in sch.col_names():
            raise ParseException("column does not exist")
        try:
            self.cat.get_index(q.table_name.lower(), q.column_name.lower())
        except IndexError_:
            raise ParseException("index not found")
