"""Checkout/lease locking and optimistic concurrency."""

from __future__ import annotations

import pytest

from account_pool.actions.locking import LockService
from account_pool.db.engine import Database
from account_pool.db.repositories import AccountRepository, VersionConflict
from account_pool.domain.enums import Platform
from account_pool.domain.ids import account_id
from account_pool.domain.models import Account
from account_pool.errors import InvalidState, LockHeld


@pytest.fixture
def accounts():
    db = Database("sqlite:///:memory:")
    db.create_all()
    repo = AccountRepository(db)
    a = Account(account_id=account_id(Platform.REDDIT, "demo"), platform=Platform.REDDIT, handle="demo")
    repo.add(a)
    return repo, a.account_id


def test_checkout_then_other_agent_blocked(accounts):
    repo, aid = accounts
    locks = LockService(repo, default_ttl_seconds=600)
    a = locks.checkout(aid, "agent-1")
    assert a.lock and a.lock.holder == "agent-1"
    assert a.record_version == 2  # checkout bumped the version
    with pytest.raises(LockHeld):
        locks.checkout(aid, "agent-2")


def test_refresh_requires_valid_token(accounts):
    repo, aid = accounts
    locks = LockService(repo, default_ttl_seconds=600)
    a = locks.checkout(aid, "agent-1")
    token = a.lock.token
    refreshed = locks.refresh(aid, "agent-1", token)
    assert refreshed.lock.expires_at >= a.lock.expires_at
    with pytest.raises(LockHeld):
        locks.refresh(aid, "agent-1", "wrong-token")


def test_checkin_releases(accounts):
    repo, aid = accounts
    locks = LockService(repo, default_ttl_seconds=600)
    a = locks.checkout(aid, "agent-1")
    token = a.lock.token
    with pytest.raises(LockHeld):
        locks.checkin(aid, "agent-2", token)
    released = locks.checkin(aid, "agent-1", token)
    assert released.lock is None
    # a fresh agent can now check out
    assert locks.checkout(aid, "agent-2").lock.holder == "agent-2"


def test_checkin_when_not_locked(accounts):
    repo, aid = accounts
    locks = LockService(repo, default_ttl_seconds=600)
    with pytest.raises(InvalidState):
        locks.checkin(aid, "agent-1", "tok")


def test_optimistic_version_conflict(accounts):
    repo, aid = accounts
    a1 = repo.get(aid)
    a2 = repo.get(aid)
    repo.update(a1, expected_version=a1.record_version)  # a1 wins
    with pytest.raises(VersionConflict):
        repo.update(a2, expected_version=a2.record_version)  # a2 is now stale
