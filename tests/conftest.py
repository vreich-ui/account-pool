"""Shared fixtures. Every app is built on an in-memory DB with a throwaway vault key, so tests touch
no real platform and no persistent state."""

from __future__ import annotations

import pytest

from account_pool.app import build_app
from account_pool.config import Settings
from account_pool.vault.keyref import generate_key


@pytest.fixture
def master_key(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("ACCOUNT_POOL_MASTER_KEY", key)
    return key


@pytest.fixture
def app(master_key):
    """A dry-run app (no real writes; adapters simulate)."""
    return build_app(Settings(database_url="sqlite:///:memory:", dry_run=True, environment="dev"))


@pytest.fixture
def app_live(master_key):
    """An app with dry_run off — the FakeAdapter records 'real' writes for assertions."""
    return build_app(Settings(database_url="sqlite:///:memory:", dry_run=False, environment="dev"))


@pytest.fixture
def make_active():
    """Factory: register -> authorize -> connect an account to ACTIVE."""

    async def _make(
        app,
        platform: str = "mastodon",
        handle: str = "brand",
        scopes=("publish", "comment", "react", "read"),
        agent: str = "agent-1",
        owner: str = "kugelbrands",
    ):
        acc = app.account_service
        a = acc.register(agent, platform, handle)
        acc.authorize(
            agent, a.account_id, owner=owner, consent_scope=list(scopes), attested_by="human-reviewer"
        )
        return await acc.connect(agent, a.account_id, "oauth2", {"access_token": "x"})

    return _make
