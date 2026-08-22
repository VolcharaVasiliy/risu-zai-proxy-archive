"""Small persistent key/value store used by Responses sessions.

The store intentionally keeps the value opaque JSON.  SQLite is the default for
local runs; deployments without a writable filesystem can select ``memory`` or
provide their own process-level adapter later without changing callers.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path


class StateStore:
    def __init__(self, backend=None, path=None):
        self.backend = (backend or os.environ.get("PROXY_STATE_BACKEND", "sqlite")).strip().lower()
        if self.backend not in {"sqlite", "memory"}:
            self.backend = "memory"
        configured = path or os.environ.get("PROXY_STATE_PATH", "")
        self.path = configured or str(Path("run") / "responses-state.sqlite3")
        self._lock = threading.RLock()
        self._memory = {}
        self._conn = None
        if self.backend == "sqlite":
            try:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(self.path, check_same_thread=False)
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
                )
                self._conn.commit()
            except Exception:
                self.backend = "memory"
                self._conn = None

    def get(self, key, ttl=None):
        key = str(key or "").strip()
        if not key:
            return None
        cutoff = time.time() - float(ttl) if ttl else None
        with self._lock:
            if self.backend == "sqlite" and self._conn:
                row = self._conn.execute("SELECT value, updated_at FROM state WHERE key=?", (key,)).fetchone()
                if not row:
                    return None
                if cutoff is not None and row[1] < cutoff:
                    self.delete(key)
                    return None
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
            item = self._memory.get(key)
            if not item or (cutoff is not None and item[1] < cutoff):
                if item:
                    self._memory.pop(key, None)
                return None
            return dict(item[0]) if isinstance(item[0], dict) else item[0]

    def put(self, key, value, updated_at=None):
        key = str(key or "").strip()
        if not key:
            return
        stamp = float(updated_at or time.time())
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if self.backend == "sqlite" and self._conn:
                self._conn.execute(
                    "INSERT INTO state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, encoded, stamp),
                )
                self._conn.commit()
            else:
                self._memory[key] = (value, stamp)

    def delete(self, key):
        key = str(key or "").strip()
        with self._lock:
            if self.backend == "sqlite" and self._conn:
                cur = self._conn.execute("DELETE FROM state WHERE key=?", (key,))
                self._conn.commit()
                return cur.rowcount > 0
            return self._memory.pop(key, None) is not None

    def prune(self, ttl):
        cutoff = time.time() - float(ttl)
        with self._lock:
            if self.backend == "sqlite" and self._conn:
                cur = self._conn.execute("DELETE FROM state WHERE updated_at < ?", (cutoff,))
                self._conn.commit()
                return cur.rowcount
            stale = [key for key, (_, stamp) in self._memory.items() if stamp < cutoff]
            for key in stale:
                self._memory.pop(key, None)
            return len(stale)

    def status(self):
        with self._lock:
            if self.backend == "sqlite" and self._conn:
                count = self._conn.execute("SELECT COUNT(*) FROM state").fetchone()[0]
            else:
                count = len(self._memory)
            return {"backend": self.backend, "path": self.path if self.backend == "sqlite" else None, "entries": count}

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


store = StateStore()
