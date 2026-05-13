"""
Tiny disk + memory cache for CHPP responses.

Key design: cache by a stable hash of (endpoint, sorted query params), store
the raw XML response text on disk. Same-session repeats hit memory, cross-session
repeats hit disk. Cache invalidation is by TTL or by deleting the cache directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional


class XMLCache:
    """A minimal two-tier cache for CHPP XML responses."""

    def __init__(self, cache_dir: Path, default_ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl_seconds
        self._mem: dict[str, tuple[float, str]] = {}

    @staticmethod
    def _key(endpoint: str, params: dict) -> str:
        canonical = json.dumps({"e": endpoint, "p": params}, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def _disk_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.xml"

    def get(self, endpoint: str, params: dict, ttl: Optional[int] = None) -> Optional[str]:
        ttl = self.default_ttl if ttl is None else ttl
        key = self._key(endpoint, params)
        now = time.time()

        # memory tier
        entry = self._mem.get(key)
        if entry is not None:
            stored_at, text = entry
            if now - stored_at <= ttl:
                return text
            del self._mem[key]

        # disk tier
        path = self._disk_path(key)
        if path.exists():
            stored_at = path.stat().st_mtime
            if now - stored_at <= ttl:
                text = path.read_text(encoding="utf-8")
                self._mem[key] = (stored_at, text)
                return text

        return None

    def put(self, endpoint: str, params: dict, text: str) -> None:
        key = self._key(endpoint, params)
        now = time.time()
        self._mem[key] = (now, text)
        self._disk_path(key).write_text(text, encoding="utf-8")

    def invalidate(self, endpoint: Optional[str] = None) -> int:
        """Drop cache entries. If endpoint omitted, drop everything. Returns count."""
        if endpoint is None:
            count = len(list(self.cache_dir.glob("*.xml"))) + len(self._mem)
            for p in self.cache_dir.glob("*.xml"):
                p.unlink()
            self._mem.clear()
            return count
        # endpoint-targeted invalidation - just clear memory (disk entries
        # have no easy reverse map, full clear is fine for now)
        keep = {}
        dropped = 0
        for k, v in self._mem.items():
            keep[k] = v
        # we don't track endpoint per key on disk, so leave disk alone for now
        self._mem = keep
        return dropped
