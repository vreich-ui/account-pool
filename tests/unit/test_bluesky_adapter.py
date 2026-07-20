"""BlueskyAdapter behavior against a fake async client (real atproto models are still built)."""

from __future__ import annotations

from account_pool.adapters.base import AdapterSession
from account_pool.adapters.bluesky import BlueskyAdapter
from account_pool.domain.enums import LifecycleState, Platform
from account_pool.domain.models import Account, ContentDraft, TargetRef
from fakes.fake_bluesky import FakeBlueskyClient


def _session() -> AdapterSession:
    account = Account(
        account_id="acct_bluesky_brand",
        platform=Platform.BLUESKY,
        handle="brand.bsky.social",
        status=LifecycleState.ACTIVE,
    )
    return AdapterSession(
        account=account, credentials={"identifier": "brand.bsky.social", "app_password": "app-pw"}
    )


def _adapter(client: FakeBlueskyClient) -> BlueskyAdapter:
    return BlueskyAdapter(client_factory=lambda creds: client)


def test_capabilities():
    caps = BlueskyAdapter().capabilities()
    assert caps.self_label_supported is True
    assert caps.can_react is True and caps.can_vote is False
    assert caps.max_text_len == 300


async def test_authenticate(bluesky_client):
    auth = await _adapter(bluesky_client).authenticate(_session())
    assert auth.ok
    assert auth.platform_user_id == "did:plc:abc123"
    assert auth.display_name == "brand.bsky.social"


async def test_self_identification_reports_label(bluesky_client):
    state = await _adapter(bluesky_client).ensure_self_identification(_session())
    assert state.self_label == "automated"


async def test_publish_dry_run_then_real(bluesky_client):
    adapter = _adapter(bluesky_client)
    draft = ContentDraft(draft_id="d", account_id="a", body="hello sky")
    dry = await adapter.publish(_session(), draft, dry_run=True)
    assert dry.dry_run and bluesky_client.posts == []
    real = await adapter.publish(_session(), draft, dry_run=False)
    assert real.ok and real.external_id.startswith("at://")
    assert bluesky_client.posts[0]["text"] == "hello sky"


async def test_comment_builds_reply_ref(bluesky_client):
    adapter = _adapter(bluesky_client)
    target = TargetRef(raw="at://did:plc:x/app.bsky.feed.post/abc", kind="post", resolved=True)
    draft = ContentDraft(draft_id="d", account_id="a", body="nice")
    res = await adapter.comment(_session(), target, draft, dry_run=False)
    assert res.ok
    assert bluesky_client.posts[-1]["reply_to"] is not None  # a ReplyRef was attached


async def test_react_like_and_repost(bluesky_client):
    adapter = _adapter(bluesky_client)
    target = TargetRef(raw="at://did:plc:x/app.bsky.feed.post/abc", resolved=True)
    await adapter.react(_session(), target, "like", dry_run=False)
    await adapter.react(_session(), target, "repost", dry_run=False)
    assert len(bluesky_client.likes) == 1
    assert len(bluesky_client.reposts) == 1


async def test_read_and_search(bluesky_client):
    adapter = _adapter(bluesky_client)
    read = await adapter.read(_session(), TargetRef(raw="at://did/app.bsky.feed.post/1", resolved=True))
    assert read.items[0]["uri"] == "at://did/app.bsky.feed.post/1"
    search = await adapter.search(_session(), "bluesky", limit=5)
    assert search.items and search.detail["query"] == "bluesky"
