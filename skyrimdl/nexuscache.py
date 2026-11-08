"""Keep what Nexus told us on disk, so looking mods up again costs no API requests.

Holds mod pages, Files tabs and requirement lists, each with the time it was
fetched. Entries older than ``max_age_days`` are fetched again; "Refresh from
Nexus" and "Check for updates" always ask Nexus.

Stored in %LOCALAPPDATA%\\SkyrimDownloaded\\nexus-cache.json (not roaming).
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from pathlib import Path

FORMAT = 1
DEFAULT_MAX_AGE_DAYS = 7


def cache_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "SkyrimDownloaded"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "skyrimdownloaded"


class DiskCache:
    def __init__(self, path: Path, max_age_days: float = DEFAULT_MAX_AGE_DAYS):
        self.path = path
        self.max_age = max_age_days * 86400
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._dirty = False
        self._timer: threading.Timer | None = None
        self.hits = 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("format") == FORMAT:
                self._entries = dict(data.get("entries") or {})
        except (OSError, ValueError, AttributeError):
            pass
        atexit.register(self.flush)

    def get(self, key: str, max_age: float | None = None):
        with self._lock:
            entry = self._entries.get(key)
        if not entry:
            return None
        age = time.time() - float(entry.get("t") or 0)
        if age > (self.max_age if max_age is None else max_age):
            return None
        self.hits += 1
        return entry.get("data")

    def has(self, key: str) -> bool:
        with self._lock:
            entry = self._entries.get(key)
        return bool(entry) and time.time() - float(entry.get("t") or 0) <= self.max_age

    def age(self, key: str) -> float | None:
        with self._lock:
            entry = self._entries.get(key)
        return None if not entry else time.time() - float(entry.get("t") or 0)

    def put(self, key: str, data) -> None:
        with self._lock:
            self._entries[key] = {"t": time.time(), "data": data}
            self._dirty = True
            if self._timer is None:  # write a moment later, once a burst of lookups settles
                self._timer = threading.Timer(3.0, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def forget(self, key: str) -> None:
        with self._lock:
            if self._entries.pop(key, None) is not None:
                self._dirty = True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._dirty = True
        self.flush()

    def __len__(self) -> int:
        return len(self._entries)

    def flush(self) -> None:
        with self._lock:
            self._timer = None
            if not self._dirty:
                return
            data = json.dumps({"format": FORMAT, "entries": self._entries})
            self._dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass


_shared: DiskCache | None = None


def shared() -> DiskCache:
    """The app's cache (one per run)."""
    global _shared
    if _shared is None:
        _shared = DiskCache(cache_dir() / "nexus-cache.json")
    return _shared
