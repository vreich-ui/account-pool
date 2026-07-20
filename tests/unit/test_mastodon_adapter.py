"""MastodonAdapter behavior against a fake sync client."""

from __future__ import annotations

from account_pool.adapters.base import AdapterSession
from account_pool.adapters.mastodon import MastodonAdapter, _status_id
from account_pool.domain.enums import LifecycleState, Platform
from account_pool.domain.models import Account, ContentDraft, TargetRef
from fakes.fake_mastodon import FakeMastodonClient


def _session() -> AdapterSession:
    account = Account(
        account_id="acct_mastodon_brand",
        platform=Platform.MASTODON,
        handle="brandmasto",
        status=LifecycleState.ACTIVE,
    )
    return AdapterSession(account=account, credentials={"access_token": "t", "api_base_url": "u"})


def _adapter(client: FakeMastodonClient) -> MastodonAdapter:
    return MastodonAdapter(client_factory=lambda creds: client)


def test_status_id():
    assert _status_id("https://mastodon.social/@user/109876543210") == "109876543210"
    assert _status_id("109") == "109"


def test_capabilities():
    caps = MastodonAdapter().capabilities()
    assert caps.requires_bot_flag is True
    assert caps.can_react is True and caps.can_vote is False
    assert caps.max_text_len == 500


async def test_authenticate(mastodon_client):
    auth = await _adapter(mastodon_client).authenticate(_session())
    assert auth.ok and auth.platform_user_id == "1"


async def test_self_identification_sets_bot_flag(mastodon_client):
    state = await _adapter(mastodon_client).ensure_self_identification(_session())
    assert state.bot_flag_set is True
    assert mastodon_client.bot is True


async def test_publish_dry_run_then_real(mastodon_client):
    adapter = _adapter(mastodon_client)
    draft = ContentDraft(draft_id="d", account_id="a", body="hello fedi")
    dry = await adapter.publish(_session(), draft, dry_run=True)
    assert dry.dry_run and mastodon_client.posted == []
    real = await adapter.publish(_session(), draft, dry_run=False)
    assert real.ok and real.external_id == "100"
    assert mastodon_client.posted[0]["body"] == "hello fedi"


async def test_comment_replies(mastodon_client):
    adapter = _adapter(mastodon_client)
    target = await adapter.resolve_target(_session(), "https://m/@u/555")
    draft = ContentDraft(draft_id="d", account_id="a", body="reply")
    await adapter.comment(_session(), target, draft, dry_run=False)
    assert mastodon_client.posted[-1]["reply_to"] == "555"


async def test_react_favourite_and_boost(mastodon_client):
    adapter = _adapter(mastodon_client)
    target = TargetRef(raw="555", parent_id="555", resolved=True)
    await adapter.react(_session(), target, "favourite", dry_run=False)
    await adapter.react(_session(), target, "boost", dry_run=False)
    assert mastodon_client.favourited == ["555"]
    assert mastodon_client.reblogged == ["555"]


async def test_read_and_search(mastodon_client):
    adapter = _adapter(mastodon_client)
    read = await adapter.read(_session(), TargetRef(raw="555", resolved=True))
    assert read.items[0]["id"] == "555"
    search = await adapter.search(_session(), "fediverse")
    assert search.items and search.detail["query"] == "fediverse"
