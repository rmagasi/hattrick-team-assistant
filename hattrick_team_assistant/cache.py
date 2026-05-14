"""
Tiny disk + memory cache for CHPP responses.

Key design: cache by a stable hash of (endpoint, sorted query params), store
the raw XML response text on disk. Same-session repeats hit memory, cross-session
repeats hit disk. Cache invalidation is by TTL or by deleting the cache directory.

A human-readable index.json sits alongside the hash-named .xml files, mapping each
hash to its endpoint, params, team id, and fetch time - so the cache folder is
browsable instead of being an opaque pile of hashes.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional


# CHPP params that identify which team/league/match a cached response belongs to.
# Used to surface a friendly "subject" in index.json.
_SUBJECT_KEYS = ("teamID", "leagueLevelUnitID", "matchID", "playerID", "youthTeamID")


class XMLCache:
    """A minimal two-tier cache for CHPP XML responses, with a readable index."""

    def __init__(self, cache_dir: Path, default_ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl_seconds
        self._mem: dict[str, tuple[float, str]] = {}
        self._index_path = self.cache_dir / "index.json"
        self._index: dict[str, dict] = self._load_index()

    # ---------- index ----------

    def _load_index(self) -> dict[str, dict]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(
            json.dumps(self._index, indent=2, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _subject(params: dict) -> Optional[str]:
        """Pull the identifying id (teamID, matchID, etc.) out of params for the index."""
        for k in _SUBJECT_KEYS:
            if k in params and params[k] not in (None, ""):
                return f"{k}={params[k]}"
        return None

    # ---------- keys / paths ----------

    @staticmethod
    def _key(endpoint: str, params: dict) -> str:
        canonical = json.dumps({"e": endpoint, "p": params}, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def _disk_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.xml"

    # ---------- get / put ----------

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

        # update the readable index
        self._index[key] = {
            "endpoint": endpoint,
            "subject": self._subject(params),
            "params": {k: v for k, v in params.items() if k != "file"},
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "fetched_epoch": int(now),
        }
        self._save_index()

    # ---------- invalidation ----------

    def invalidate(self, endpoint: Optional[str] = None) -> int:
        """Drop cache entries. If endpoint omitted, drop everything. Returns count dropped."""
        if endpoint is None:
            count = len(list(self.cache_dir.glob("*.xml"))) + len(self._mem)
            for p in self.cache_dir.glob("*.xml"):
                p.unlink()
            self._mem.clear()
            self._index.clear()
            self._save_index()
            return count

        # endpoint-targeted: the index gives us the reverse map, so we can be precise
        dropped = 0
        for key, meta in list(self._index.items()):
            if meta.get("endpoint") == endpoint:
                disk = self._disk_path(key)
                if disk.exists():
                    disk.unlink()
                self._mem.pop(key, None)
                del self._index[key]
                dropped += 1
        self._save_index()
        return dropped
