"""Very small page‑cache layer (fixed 4 KiB pages)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

PAGE_SIZE = 4096  # bytes

class BufferManager:
    def __init__(self, data_dir: Path):
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, bytearray] = {}

    def _fp(self, table: str) -> Path:
        """return path to the file for the given table."""
        return self._dir / f"{table}.dat"

    def read_page(self, table: str, page_no: int) -> bytes:
        key = f"{table}:{page_no}"
        if key in self._cache:
            return self._cache[key]
        fp = self._fp(table)
        if not fp.exists():
            return b""  # empty -> caller treats as EOF
        with fp.open("rb") as f:
            f.seek(page_no * PAGE_SIZE)
            data = f.read(PAGE_SIZE)
        self._cache[key] = bytearray(data)
        return data

    def write_page(self, table: str, page_no: int, data: bytes) -> None:
        if len(data) > PAGE_SIZE:
            raise ValueError("Page overflow")
        fp = self._fp(table)
        fp.parent.mkdir(parents=True, exist_ok=True)
        with fp.open("r+b" if fp.exists() else "wb") as f:
            f.seek(page_no * PAGE_SIZE)
            f.write(data.ljust(PAGE_SIZE, b"\x00"))
        self._cache[f"{table}:{page_no}"] = bytearray(data)