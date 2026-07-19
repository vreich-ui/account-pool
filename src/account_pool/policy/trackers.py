"""Heuristic trackers for manipulation/coordination and self-promotion.

Both are process-local for v1 and pair with the approval gate (they are heuristics, not perfect
detectors). ``is_promotional`` classifies a draft by whether it links to a domain the owner controls.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .. import clock
from ..domain.models import Account, ContentDraft

_URL_RE = re.compile(r"https?://([^/\s]+)", re.IGNORECASE)


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


# React kinds that count as up/down voting — hard-blocked where a platform disallows it.
VOTE_KINDS: frozenset[str] = frozenset({"up", "down", "upvote", "downvote", "vote", "+1", "-1"})


def is_promotional(draft: ContentDraft, account: Account) -> bool:
    """A draft is promotional if it links to a domain the account's owner controls."""
    owned = {_strip_www(d.lower()) for d in account.persona.owned_domains}
    if not owned:
        return False
    for raw_host in _URL_RE.findall(draft.body):
        host = _strip_www(raw_host.lower())
        if any(host == d or host.endswith("." + d) for d in owned):
            return True
    return False


class SelfPromoLedger:
    """Counts promotional vs non-promotional writes per account to enforce a ratio.

    Rule: at most ``floor(non_promo / ratio)`` promotional writes. With ratio 9 this approximates
    Reddit's 90/10 guideline — a promo post is allowed only once enough non-promo activity exists.
    """

    def __init__(self) -> None:
        self._promo: dict[str, int] = defaultdict(int)
        self._non_promo: dict[str, int] = defaultdict(int)

    def would_exceed(self, account_id: str, ratio: int) -> bool:
        if ratio <= 0:
            return False
        allowed = self._non_promo[account_id] // ratio
        return self._promo[account_id] >= allowed

    def record(self, account_id: str, promotional: bool) -> None:
        if promotional:
            self._promo[account_id] += 1
        else:
            self._non_promo[account_id] += 1

    def counts(self, account_id: str) -> tuple[int, int]:
        return self._promo[account_id], self._non_promo[account_id]


class CoordinationTracker:
    """Flags several pool accounts acting on the same target within a window (astroturf pattern)."""

    def __init__(self, window_seconds: float = 300.0, max_distinct_accounts: int = 3) -> None:
        self._window = window_seconds
        self._max = max_distinct_accounts
        self._hits: dict[str, list[tuple[str, float]]] = defaultdict(list)

    def _prune(self, target_key: str, now: float) -> None:
        cutoff = now - self._window
        self._hits[target_key] = [(a, t) for a, t in self._hits[target_key] if t >= cutoff]

    def would_coordinate(self, target_key: str, account_id: str) -> bool:
        if not target_key:
            return False
        now = clock.now().timestamp()
        self._prune(target_key, now)
        distinct = {a for a, _ in self._hits[target_key]}
        distinct.add(account_id)
        return len(distinct) > self._max

    def record(self, target_key: str, account_id: str) -> None:
        if not target_key:
            return
        self._hits[target_key].append((account_id, clock.now().timestamp()))
