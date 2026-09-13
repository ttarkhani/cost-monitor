import time
from threading import Lock

# Simple in-memory TTL cache. Good enough for a single-process Flask app;
# would need Redis only if this ran across multiple server processes.
_lock = Lock()
_store = {}  # key -> (value, expires_at)
_stats = {"hits": 0, "misses": 0}


def get(key):
    with _lock:
        entry = _store.get(key)
        if entry is None:
            _stats["misses"] += 1
            return None

        value, expires_at = entry
        if time.time() >= expires_at:
            del _store[key]
            _stats["misses"] += 1
            return None

        _stats["hits"] += 1
        return value


def set(key, value, ttl_seconds=60):
    with _lock:
        _store[key] = (value, time.time() + ttl_seconds)


def get_stats():
    with _lock:
        hits = _stats["hits"]
        misses = _stats["misses"]
        total = hits + misses
        hit_rate = round((hits / total) * 100, 1) if total else 0.0
        return {"hits": hits, "misses": misses, "hit_rate_pct": hit_rate}


def clear():
    with _lock:
        _store.clear()
        _stats["hits"] = 0
        _stats["misses"] = 0