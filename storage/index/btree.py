"""thin wrapper for any dict-like B‑tree (fallback to dict if unavailable)."""
from __future__ import annotations

try:
    from bintrees import RBTree  # type: ignore
except ImportError: 
    RBTree = dict  # default to dict ~ log‑time for small datasets

import json
from pathlib import Path
from typing import Any, Optional, List, Tuple

class BTreeIndex:
    def __init__(self, path: Path):
        self.path = path
        self.tree = RBTree() if RBTree is not dict else {}
        if path.exists():
            self._load()

    def _load(self):
        data = json.loads(self.path.read_text())
        for k, v in data.items():
            # Attempt to convert keys back to int if they were originally int
            try:
                key = int(k)
            except ValueError:
                key = k 
            self.tree[key] = v

    def _flush(self):
        # Convert tree keys to strings for JSON compatibility
        data_to_dump = {str(k): v for k, v in self.tree.items()}
        self.path.write_text(json.dumps(data_to_dump))

    def insert(self, key: Any, offset: int):
        """Inserts a single key-offset pair and flushes immediately."""
        if key in self.tree:
            raise ValueError(f"Duplicate key in index: {key}")
        self.tree[key] = offset
        self._flush() # Flush after single insert

    def insert_many(self, items: List[Tuple[Any, int]]):
        """Inserts a batch of key-offset pairs and flushes once at the end."""
        if not items:
            return
            
        batch_keys = set()
        for key, offset in items:
            if key in self.tree:
                 raise ValueError(f"Duplicate key in index (already exists): {key}")
            if key in batch_keys:
                 raise ValueError(f"Duplicate key in index (within batch): {key}")
            batch_keys.add(key)
        
        # All keys validated, now perform batch insert into memory
        for key, offset in items:
            self.tree[key] = offset
            
        self._flush() # Flush once after all in-memory updates

    def search(self, key: Any) -> Optional[int]:
        return self.tree.get(key)

    # Add delete and potentially update methods if needed later, ensuring they flush.
    def delete(self, key: Any):
        """Deletes a key and flushes."""
        if key in self.tree:
            del self.tree[key]
            self._flush()