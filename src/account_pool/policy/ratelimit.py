"""In-memory rolling-window rate limiter (per account + verb).

``check`` is non-consuming so a downstream guard denial doesn't waste budget; the actions service
calls ``consume`` only when an action actually executes. v1 is process-local; a shared store
(Redis/Postgres) slots in behind the same interface later.
"""

from __future__ import annotations

from collections import defaultdict

from .. import clock

_WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def _key(account_id: str, action: str) -> str:
        return f"{account_id}:{action}"

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        self._events[key] = [t for t in self._events[key] if t >= cutoff]

    def check(self, account_id: str, action: str, limit_per_min: int) -> bool:
        """True if another action is allowed within the window (does not consume)."""
        if limit_per_min <= 0:
            return True  # 0/unset => unlimited
        key = self._key(account_id, action)
        now = clock.now().timestamp()
        self._prune(key, now)
        return len(self._events[key]) < limit_per_min

    def consume(self, account_id: str, action: str) -> None:
        key = self._key(account_id, action)
        now = clock.now().timestamp()
        self._prune(key, now)
        self._events[key].append(now)

    def snapshot(self, account_id: str, action: str) -> int:
        key = self._key(account_id, action)
        self._prune(key, clock.now().timestamp())
        return len(self._events[key])
