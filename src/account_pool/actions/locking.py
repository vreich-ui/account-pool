"""Checkout/lease locking.

Atomicity comes from the repository's optimistic ``record_version`` compare-and-set: two agents
racing to check out the same account both read version *v*; only one's update (expected *v*)
succeeds, the other retries, sees the active lease, and gets :class:`LockHeld`.
"""

from __future__ import annotations

from datetime import timedelta

from .. import clock
from ..config import get_settings
from ..db.repositories import AccountRepository, VersionConflict
from ..domain.ids import lock_token as new_lock_token
from ..domain.models import Account, LockLease
from ..errors import Conflict, InvalidState, LockHeld, NotFound

_MAX_CAS_RETRIES = 4


class LockService:
    def __init__(self, accounts: AccountRepository, default_ttl_seconds: int | None = None) -> None:
        self._accounts = accounts
        self._default_ttl = default_ttl_seconds or get_settings().default_lock_ttl_seconds

    def _get(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise NotFound(f"account '{account_id}' not found")
        return account

    def checkout(self, account_id: str, holder: str, ttl_seconds: int | None = None) -> Account:
        ttl = ttl_seconds or self._default_ttl
        for _ in range(_MAX_CAS_RETRIES):
            account = self._get(account_id)
            now = clock.now()
            if account.lock and account.lock.is_active(now) and account.lock.holder != holder:
                raise LockHeld(f"account checked out by '{account.lock.holder}'")
            expected = account.record_version
            account.lock = LockLease(
                holder=holder,
                token=new_lock_token(),
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
            try:
                return self._accounts.update(account, expected_version=expected)
            except VersionConflict:
                continue  # lost the race — re-read and re-evaluate
        raise Conflict("could not acquire lock (contention)")

    def refresh(self, account_id: str, holder: str, token: str, ttl_seconds: int | None = None) -> Account:
        ttl = ttl_seconds or self._default_ttl
        account = self._get(account_id)
        lock = account.lock
        if lock is None or not lock.held_by(holder, token):
            raise LockHeld("you do not hold an active lock on this account")
        expected = account.record_version
        now = clock.now()
        account.lock = LockLease(
            holder=holder,
            token=token,
            acquired_at=lock.acquired_at,
            expires_at=now + timedelta(seconds=ttl),
        )
        try:
            return self._accounts.update(account, expected_version=expected)
        except VersionConflict as e:
            raise Conflict("lock refresh lost a concurrency race; retry") from e

    def checkin(self, account_id: str, holder: str, token: str) -> Account:
        account = self._get(account_id)
        lock = account.lock
        if lock is None:
            raise InvalidState("account is not checked out")
        if not (lock.holder == holder and lock.token == token):
            raise LockHeld("only the lock holder may check the account in")
        expected = account.record_version
        account.lock = None
        try:
            return self._accounts.update(account, expected_version=expected)
        except VersionConflict as e:
            raise Conflict("checkin lost a concurrency race; retry") from e
