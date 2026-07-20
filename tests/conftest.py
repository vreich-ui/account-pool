"""Shared fixtures. Every app is built on an in-memory DB with a throwaway vault key, so tests touch
no real platform and no persistent state."""

from __future__ import annotations

import pytest

from account_pool.app import build_app
from account_pool.config import Settings
from account_pool.vault.keyref import generate_key
from fakes.fake_reddit import FakeRedditClient, reddit_registry


@pytest.fixture
def master_key(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("ACCOUNT_POOL_MASTER_KEY", key)
    return key


@pytest.fixture
def reddit_client():
    """A shared fake asyncpraw client; assert on its recorded writes."""
    return FakeRedditClient(username="brand_reddit")


@pytest.fixture
def reddit_app(master_key, reddit_client):
    """A dry-run app whose Reddit platform is backed by the real RedditAdapter + a fake client."""
    return build_app(
        Settings(database_url="sqlite:///:memory:", dry_run=True, environment="dev"),
        registry=reddit_registry(reddit_client),
    )


@pytest.fixture
def reddit_app_live(master_key, reddit_client):
    """Like ``reddit_app`` but with dry_run off, so real submits reach the fake client."""
    return build_app(
        Settings(database_url="sqlite:///:memory:", dry_run=False, environment="dev"),
        registry=reddit_registry(reddit_client),
    )


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


def _real_app(master_key, registry, *, dry_run):
    return build_app(
        Settings(database_url="sqlite:///:memory:", dry_run=dry_run, environment="dev"),
        registry=registry,
    )


@pytest.fixture
def mastodon_client():
    from fakes.fake_mastodon import FakeMastodonClient

    return FakeMastodonClient()


@pytest.fixture
def mastodon_app(master_key, mastodon_client):
    from fakes.fake_mastodon import mastodon_registry

    return _real_app(master_key, mastodon_registry(mastodon_client), dry_run=True)


@pytest.fixture
def mastodon_app_live(master_key, mastodon_client):
    from fakes.fake_mastodon import mastodon_registry

    return _real_app(master_key, mastodon_registry(mastodon_client), dry_run=False)


@pytest.fixture
def bluesky_client():
    from fakes.fake_bluesky import FakeBlueskyClient

    return FakeBlueskyClient()


@pytest.fixture
def bluesky_app(master_key, bluesky_client):
    from fakes.fake_bluesky import bluesky_registry

    return _real_app(master_key, bluesky_registry(bluesky_client), dry_run=True)


@pytest.fixture
def bluesky_app_live(master_key, bluesky_client):
    from fakes.fake_bluesky import bluesky_registry

    return _real_app(master_key, bluesky_registry(bluesky_client), dry_run=False)


@pytest.fixture
def twitter_client():
    from fakes.fake_twitter import FakeTweepyClient

    return FakeTweepyClient()


@pytest.fixture
def twitter_app(master_key, twitter_client):
    from fakes.fake_twitter import twitter_registry

    return _real_app(master_key, twitter_registry(twitter_client), dry_run=True)


@pytest.fixture
def twitter_app_live(master_key, twitter_client):
    from fakes.fake_twitter import twitter_registry

    return _real_app(master_key, twitter_registry(twitter_client), dry_run=False)
