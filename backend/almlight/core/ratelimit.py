"""Counters for failed sign-in attempts (in memory, per process).

One application process serves all users (live editing needs that anyway), so a sliding window per key is enough;
a restart clears the counters. Keys are user names, client addresses and users changing their password.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

MAX_KEYS = 10_000  # bounds the memory used by guessed user names


class FailureLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def _pruned(self, key: str, window: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        cutoff = self._clock() - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _evict(self, window: float) -> None:
        for key in list(self._hits):
            self._pruned(key, window)
        if len(self._hits) >= MAX_KEYS:  # still full: forget the keys that failed longest ago
            oldest = sorted(self._hits, key=lambda k: self._hits[k][-1])[: MAX_KEYS // 2]
            for key in oldest:
                del self._hits[key]

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until another attempt is allowed for this key (0 = allowed now, also when the limit is off)."""
        if limit <= 0:
            return 0
        with self._lock:
            hits = self._pruned(key, window)
            if hits is None or len(hits) < limit:
                return 0
            return max(1, int(hits[len(hits) - limit] + window - self._clock()) + 1)

    def record(self, key: str, window: float) -> int:
        """Count one failure; returns the number of failures within the window."""
        with self._lock:
            hits = self._pruned(key, window)
            if hits is None:
                if len(self._hits) >= MAX_KEYS:
                    self._evict(window)
                hits = self._hits[key] = deque()
            hits.append(self._clock())
            return len(hits)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_failures = FailureLimiter()
