"""thin wrapper for any dict-like B‑tree (fallback to dict if unavailable)."""
from __future__ import annotations

try:
    from bintrees import RBTree  # type: ignore
except ImportError: 
    RBTree = dict  # default to dict ~ log‑time for small datasets

import json
from pathlib import Path
from typing import Any, Optional

class BTreeIndex:
    def __init__(self, path: Path):
        self.path = path
        self.tree = RBTree() if RBTree is not dict else {}
        if path.exists():
            self._load()

    def _load(self):
        data = json.loads(self.path.read_text())
        for k, v in data.items():
            self.tree[int(k) if k.isdigit() else k] = v

    def _flush(self):
        self.path.write_text(json.dumps(self.tree))

    def insert(self, key: Any, offset: int):
        if key in self.tree:
            raise ValueError("Duplicate key in index")
        self.tree[key] = offset
        self._flush()

    def search(self, key: Any) -> Optional[int]:
        return self.tree.get(key)