"""HeapFile is a unsorted collection of fixed‑schema rows (tuple of fields).
records are stored row‑wise; variable‑length strings are UTF‑8‑encoded with length prefix.
pk uniqueness is validated with the catalog index.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator, List, Tuple

from catalog import Catalog
from .buffer_manager import BufferManager, PAGE_SIZE
from .index.btree import BTreeIndex  # thin wrapper

__all__ = ["HeapFile"]

class HeapFile:
    """High‑level table interface (append, scan, get_by_pk)."""

    def __init__(self, catalog: Catalog, data_dir: str | os.PathLike, table: str):
        self.catalog = catalog
        self.table = table.lower()
        self.schema = catalog.get_schema(self.table)  # raises if unknown
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.buf = BufferManager(self.dir)
        # pk index lives beside the heap file
        self.pk_index: BTreeIndex | None = None
        if self.schema.primary_key:
            self.pk_index = BTreeIndex(self.dir / f"{self.table}.pk.index")

    # helpers
    def _encode_row(self, row: Tuple[Any, ...]) -> bytes:
        return json.dumps(row).encode("utf‑8") + b"\n"

    def _decode_row(self, raw: bytes) -> Tuple[Any, ...]:
        return tuple(json.loads(raw))

    # public api
    def insert(self, *values):
        if len(values) != len(self.schema.columns):
            raise ValueError("Column count mismatch")
        # basic type checks – int vs str
        for v, col in zip(values, self.schema.columns):
            if col.type == "INT" and not isinstance(v, int):
                raise TypeError(f"Expected INT for {col.name}")
            if col.type == "STR" and not isinstance(v, str):
                raise TypeError(f"Expected STR for {col.name}")
        # pk uniqueness via index
        if self.pk_index is not None:
            pk_val = values[self.schema.col_names().index(self.schema.primary_key)]
            if self.pk_index.search(pk_val) is not None:
                raise ValueError("Duplicate primary key")
        # append to heap file
        fp = self.dir / f"{self.table}.dat"
        with fp.open("ab") as f:
            pos = f.tell()
            f.write(self._encode_row(values))
        # update index
        if self.pk_index is not None:
            self.pk_index.insert(pk_val, pos)

    def scan(self) -> Iterator[Tuple[Any, ...]]:
        fp = self.dir / f"{self.table}.dat"
        if not fp.exists():
            return iter(())
        with fp.open("rb") as f:
            for line in f:
                if not line.strip():
                    continue
                yield self._decode_row(line)

    def get_by_pk(self, key) -> Tuple[Any, ...] | None:
        if self.pk_index is None:
            raise RuntimeError("No primary key defined")
        offset = self.pk_index.search(key)
        if offset is None:
            return None
        fp = self.dir / f"{self.table}.dat"
        with fp.open("rb") as f:
            f.seek(offset)
            return self._decode_row(f.readline())
    
    def delete(self, pk_val):
        """Delete a row by primary key"""
        if self.pk_index is None:
            raise RuntimeError("No primary key defined")
            
        offset = self.pk_index.search(pk_val)
        if offset is None:
            return  # nothing to delete
            
        # create a new data file without the deleted record
        fp = self.dir / f"{self.table}.dat"
        temp_fp = self.dir / f"{self.table}.tmp"
        
        # create a new index for the restructured file
        old_index_path = self.dir / f"{self.table}.pk.index"
        backup_index_path = self.dir / f"{self.table}.pk.index.bak"
        
        # create a new empty index - not sure if this is needed
        if old_index_path.exists():
            if backup_index_path.exists():
                backup_index_path.unlink()
            old_index_path.rename(backup_index_path)
            
        # create new index
        self.pk_index = BTreeIndex(old_index_path)
        
        with fp.open("rb") as src, temp_fp.open("wb") as dst:
            current_pos = 0
            new_pos = 0
            
            for line in src:
                if current_pos == offset:
                    # skip this record (it's being deleted)
                    current_pos += len(line)
                    continue
                    
                # copy this record to the new file
                dst.write(line)
                
                # update index for this record if needed
                if self.pk_index is not None:
                    row = self._decode_row(line)
                    pk_idx = self.schema.col_names().index(self.schema.primary_key)
                    row_pk = row[pk_idx]
                    self.pk_index.insert(row_pk, new_pos)
                
                current_pos += len(line)
                new_pos += len(line)
        
        # replace old file with new file
        fp.unlink()
        temp_fp.rename(fp)
    
    def update(self, pk_val, *new_values):
        """Update a row by primary key with new values"""
        #  implement update as delete + insert
        if self.pk_index is None:
            raise RuntimeError("No primary key defined")
            
        # check if record exists before updating
        if self.get_by_pk(pk_val) is None:
            return  # nothing to update
            
        self.delete(pk_val)
        
        self.insert(*new_values)
            
            
