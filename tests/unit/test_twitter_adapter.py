"""TwitterAdapter behavior against a fake tweepy client."""

from __future__ import annotations

import pytest

from account_pool.adapters.base import AdapterSession, UnsupportedCapability
from account_pool.adapters.twitter import TwitterAdapter, _tweet_id
from account_pool.domain.enums import LifecycleState, Platform
from account_pool.domain.models import Account, ContentDraft, TargetRef
from fakes.fake_twitter import FakeTweepyClient


def _session() -> AdapterSession:
    account = Account(
        account_id="acct_twitter_brand",
        platform=Platform.TWITTER,
        handle="brandx",
        status=LifecycleState.ACTIVE,
    )
    return AdapterSession(account=account, credentials={"bearer_token": "b"})


def _adapter(client: FakeTweepyClient, **kw) -> TwitterAdapter:
    return TwitterAdapter(client_factory=lambda creds: client, **kw)


def test_tweet_id():
    assert _tweet_id("https://twitter.com/user/status/1789012345678") == "1789012345678"
    assert _tweet_id("1789") == "1789"


def test_capabilities():
    caps = TwitterAdapter().capabilities()
    assert caps.max_text_len == 280
    assert caps.can_react is True and caps.can_vote is False
    assert caps.requires_bot_flag is False


def test_reads_disabled_capabilities():
    caps = TwitterAdapter(reads_enabled=False).capabilities()
    assert caps.can_read is False and caps.can_search is False


async def test_reads_disabled_raises(twitter_client):
    adapter = _adapter(twitter_client, reads_enabled=False)
    with pytest.raises(UnsupportedCapability):
        await adapter.read(_session(), TargetRef(raw="1", resolved=True))


async def test_authenticate(twitter_client):
    auth = await _adapter(twitter_client).authenticate(_session())
    assert auth.ok and auth.platform_user_id == "42" and auth.display_name == "brandx"


async def test_publish_dry_then_real(twitter_client):
    adapter = _adapter(twitter_client)
    draft = ContentDraft(draft_id="d", account_id="a", body="gm")
    dry = await adapter.publish(_session(), draft, dry_run=True)
    assert dry.dry_run and twitter_client.tweets == []
    real = await adapter.publish(_session(), draft, dry_run=False)
    assert real.ok and real.external_id == "1000"
    assert twitter_client.tweets[0]["text"] == "gm"


async def test_comment_reply(twitter_client):
    adapter = _adapter(twitter_client)
    target = await adapter.resolve_target(_session(), "https://x.com/u/status/555")
    draft = ContentDraft(draft_id="d", account_id="a", body="reply")
    await adapter.comment(_session(), target, draft, dry_run=False)
    assert twitter_client.tweets[-1]["reply_to"] == "555"


async def test_react_like_and_retweet(twitter_client):
    adapter = _adapter(twitter_client)
    target = TargetRef(raw="555", parent_id="555", resolved=True)
    await adapter.react(_session(), target, "like", dry_run=False)
    await adapter.react(_session(), target, "retweet", dry_run=False)
    assert twitter_client.likes == ["555"] and twitter_client.retweets == ["555"]


async def test_read_and_search(twitter_client):
    adapter = _adapter(twitter_client)
    read = await adapter.read(_session(), TargetRef(raw="555", resolved=True))
    assert read.items[0]["id"] == "555"
    search = await adapter.search(_session(), "brand", limit=10)
    assert len(search.items) == 2 and search.detail["query"] == "brand"
