"""system catalog implementation:

- presists TABLES and COLUMNS in‑memory *and* on disk (JSON).
- enforced invariants (unique names for tables and columns, PK presence, FK targets).

presisted file: `.rdbms_catalog.json` in project root - created on first run and updated on each commit.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

__all__ = ["Catalog", "CatalogError", "Column", "TableSchema"]

CATALOG_PATH = os.environ.get("RDBMS_CATALOG", ".rdbms_catalog.json")

# exceptions
class CatalogError(RuntimeError):
    """base class for all catalog‑related failures."""


class DuplicateTableError(CatalogError):
    pass


class UnknownTableError(CatalogError):
    pass


class DuplicateColumnError(CatalogError):
    pass


class UnknownColumnError(CatalogError):
    pass


class IndexError_(CatalogError):  # to avoid name clash with the built‑in IndexError
    pass

# json serialisable data classes
@dataclass
class Column:
    name: str
    type: str  # e.g "INT", "STR"


@dataclass
class TableSchema:
    name: str
    columns: List[Column]
    primary_key: Optional[str] = None  # column name
    indexes: List[str] | None = None   # list of indexed column names

    # fk mapping: local_col -> (foreign_table, foreign_col)
    foreign_keys: Dict[str, Tuple[str, str]] | None = None

    # runtime helpers – not persisted
    def col_names(self) -> List[str]:
        return [c.name for c in self.columns]

class Catalog:
    """holds all table schemas and persists them to the json file."""

    def __init__(self) -> None:
        self._tables: Dict[str, TableSchema] = {}
        self._load()

    # persistence
    def _load(self) -> None:
        if not os.path.exists(CATALOG_PATH):  # first run
            return
        with open(CATALOG_PATH, "r", encoding="utf‑8") as f:
            raw = json.load(f)
        for t in raw.values():
            self._tables[t["name"]] = TableSchema(
                name=t["name"],
                columns=[Column(**c) for c in t["columns"]],
                primary_key=t.get("primary_key"),
                indexes=t.get("indexes") or [],
                foreign_keys=t.get("foreign_keys") or {},
            )

    def _flush(self) -> None:
        """updates the persisted catalog file. ensures the catalog is never left in partial state."""
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="catalog_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf‑8") as f:
                json.dump({k: asdict(v) for k, v in self._tables.items()}, f, indent=2)
            os.replace(tmp_path, CATALOG_PATH)
        finally:
            # ensures the temp file is removed on error
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # public apis
    def list_tables(self) -> List[str]:
        return sorted(self._tables)

    def get_schema(self, table: str) -> TableSchema:
        if table not in self._tables:
            raise UnknownTableError(table)
        return self._tables[table]

    # ddl helpers
    def create_table(
        self,
        name: str,
        columns: List[Tuple[str, str]],
        primary_key: Optional[str] = None,
        foreign_keys: Optional[Dict[str, Tuple[str, str]]] = None,
    ) -> None:
        name = name.lower()
        if name in self._tables:
            raise DuplicateTableError(name) 

        col_objs = []
        seen = set()
        for col_name, col_type in columns:
            col_name = col_name.lower()
            if col_name in seen:
                raise DuplicateColumnError(col_name)
            seen.add(col_name)
            if col_type.upper() not in ("INT", "STRING", "STR"):
                raise CatalogError(f"Unsupported type: {col_type}")
            col_objs.append(Column(col_name, "INT" if col_type.upper() == "INT" else "STR"))
        if primary_key and primary_key.lower() not in seen:
            raise UnknownColumnError(primary_key)

        # sanity checks for fk: foreign table and column must exist
        fk_map = {}
        if foreign_keys:
            for local_col, (ref_table, ref_col) in foreign_keys.items():
                if local_col.lower() not in seen:
                    raise UnknownColumnError(local_col)
                target_schema = self._tables.get(ref_table.lower())
                if not target_schema or ref_col.lower() not in target_schema.col_names():
                    raise CatalogError("FK target does not exist: %s" % ((ref_table, ref_col),))
                fk_map[local_col.lower()] = (ref_table.lower(), ref_col.lower())

        self._tables[name] = TableSchema(
            name,
            col_objs,
            primary_key.lower() if primary_key else None,
            indexes=[primary_key.lower()] if primary_key else [],
            foreign_keys=fk_map,
        )
        self._flush()

    def drop_table(self, name: str) -> None:
        name = name.lower()
        if name not in self._tables:
            raise UnknownTableError(name)
        # handle fk dependencies
        for schema in self._tables.values():
            if schema.foreign_keys and any(t == name for _, (t, _) in schema.foreign_keys.items()):
                raise CatalogError(f"Table {name} referenced by FK; cannot drop")
        del self._tables[name]
        self._flush()

    # index helpers
    def create_index(self, table: str, column: str) -> None:
        schema = self.get_schema(table.lower())
        if column.lower() not in schema.col_names():
            raise UnknownColumnError(column)
        if column.lower() in schema.indexes:
            raise IndexError_("Index already exists")
        schema.indexes.append(column.lower())
        self._flush()
    
    def get_index(self, table: str, column: str) -> None:
        schema = self.get_schema(table.lower())
        if column.lower() not in schema.col_names():
            raise UnknownColumnError(column)
        if column.lower() not in schema.indexes:
            raise IndexError_("Index does not exist")
        # get column id in indexes list
        return schema.indexes.index(column.lower()) 

    def drop_index(self, table: str, column: str) -> None:
        schema = self.get_schema(table.lower())
        try:
            schema.indexes.remove(column.lower())
        except ValueError:
            raise IndexError_("No such index") from None
        self._flush()

    # for tests ONLY - nuke all metadata
    def reset(self) -> None:
        self._tables.clear()
        if os.path.isfile(CATALOG_PATH):
            os.remove(CATALOG_PATH)