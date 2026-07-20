"""RedditAdapter behavior, driven by a fake client (no network)."""

from __future__ import annotations

import pytest

from account_pool.adapters.base import AdapterSession, ContentInvalid, UnsupportedCapability
from account_pool.adapters.reddit import RedditAdapter, parse_ref
from account_pool.domain.enums import HealthStatus, LifecycleState, Platform
from account_pool.domain.models import Account, ContentDraft, TargetRef
from fakes.fake_reddit import FakeRedditClient


def _session(handle: str = "brand_reddit") -> AdapterSession:
    account = Account(
        account_id="acct_reddit_brand",
        platform=Platform.REDDIT,
        handle=handle,
        status=LifecycleState.ACTIVE,
    )
    return AdapterSession(account=account, credentials={"username": handle})


def _adapter(client: FakeRedditClient) -> RedditAdapter:
    return RedditAdapter(client_factory=lambda creds: client)


# ---- reference parsing ----
@pytest.mark.parametrize(
    "raw,kind,id_,sub",
    [
        ("t3_abc123", "submission", "abc123", None),
        ("t1_def456", "comment", "def456", None),
        ("https://www.reddit.com/r/python/comments/abc123/some_title/", "submission", "abc123", "python"),
        ("https://www.reddit.com/r/python/comments/abc123/some_title/def456/", "comment", "def456", "python"),
        ("r/Python", "subreddit", "Python", "Python"),
        ("/u/some_user", "user", "some_user", "u_some_user"),
        ("xyz789", "submission", "xyz789", None),
    ],
)
def test_parse_ref(raw, kind, id_, sub):
    ref = parse_ref(raw)
    assert ref["kind"] == kind
    assert ref["id"] == id_
    assert ref["subreddit"] == sub


def test_capabilities():
    caps = RedditAdapter().capabilities()
    assert caps.can_publish and caps.can_comment and caps.can_read and caps.can_search
    assert caps.can_react is False  # reacting == voting, not offered
    assert caps.can_vote is True  # capability present but policy-hard-blocked
    assert caps.requires_bot_flag is False
    assert caps.max_text_len == 40000


async def test_authenticate(reddit_client):
    auth = await _adapter(reddit_client).authenticate(_session())
    assert auth.ok
    assert auth.platform_user_id == "t2_brand_reddit"
    assert auth.display_name == "brand_reddit"


async def test_ensure_self_identification_is_ok_without_bot_flag(reddit_client):
    state = await _adapter(reddit_client).ensure_self_identification(_session())
    assert state.ok  # Reddit has no bot flag; compliance is via UA + rules + rate limits


async def test_publish_requires_title(reddit_client):
    draft = ContentDraft(draft_id="d", account_id="a", body="body, no title")
    with pytest.raises(ContentInvalid):
        await _adapter(reddit_client).publish(_session(), draft, dry_run=False)


async def test_publish_dry_run_makes_no_submission(reddit_client):
    draft = ContentDraft(draft_id="d", account_id="a", title="Hello", body="body")
    res = await _adapter(reddit_client).publish(_session(), draft, dry_run=True)
    assert res.ok and res.dry_run
    assert res.detail["subreddit"] == "u_brand_reddit"
    assert reddit_client.submitted == []  # nothing really submitted


async def test_publish_real_submits_to_own_profile(reddit_client):
    draft = ContentDraft(draft_id="d", account_id="a", title="Hello", body="body")
    res = await _adapter(reddit_client).publish(_session(), draft, dry_run=False)
    assert res.ok and not res.dry_run
    assert res.external_id == "t3_newpost"
    assert len(reddit_client.submitted) == 1
    assert reddit_client.submitted[0].subreddit == "u_brand_reddit"
    assert reddit_client.closed is True  # client is closed after the call


async def test_comment_replies_to_submission(reddit_client):
    adapter = _adapter(reddit_client)
    target = await adapter.resolve_target(_session(), "t3_abc123")
    draft = ContentDraft(draft_id="d", account_id="a", body="great post")
    res = await adapter.comment(_session(), target, draft, dry_run=False)
    assert res.ok
    assert res.external_id == "t1_reply1"


async def test_comment_dry_run(reddit_client):
    adapter = _adapter(reddit_client)
    target = TargetRef(raw="t3_abc", kind="submission", resolved=True)
    draft = ContentDraft(draft_id="d", account_id="a", body="hi")
    res = await adapter.comment(_session(), target, draft, dry_run=True)
    assert res.ok and res.dry_run


async def test_read_submission_and_comment(reddit_client):
    adapter = _adapter(reddit_client)
    sub = await adapter.read(_session(), TargetRef(raw="t3_abc123", resolved=True))
    assert sub.items[0]["selftext"] is not None
    com = await adapter.read(_session(), TargetRef(raw="t1_def456", resolved=True))
    assert com.items[0]["kind"] == "comment"


async def test_search(reddit_client):
    adapter = _adapter(reddit_client)
    scoped = await adapter.search(_session(), "r/python asyncpraw", limit=5)
    assert scoped.detail["subreddit"] == "python"
    assert scoped.detail["query"] == "asyncpraw"
    assert len(scoped.items) >= 1
    unscoped = await adapter.search(_session(), "just terms")
    assert unscoped.detail["subreddit"] == "all"


async def test_health_check_ok_and_reauth():
    ok = await _adapter(FakeRedditClient(authed=True)).health_check(_session())
    assert ok.status == HealthStatus.OK
    reauth = await _adapter(FakeRedditClient(authed=False)).health_check(_session())
    assert reauth.status == HealthStatus.REAUTH_NEEDED


async def test_resolve_target_ownership(reddit_client):
    adapter = _adapter(reddit_client)
    # A target in the account's own profile subreddit is owned.
    owned = await adapter.resolve_target(
        _session(), "https://www.reddit.com/r/u_brand_reddit/comments/abc/mine/"
    )
    assert owned.is_owned is True
    third = await adapter.resolve_target(_session(), "https://www.reddit.com/r/python/comments/abc/theirs/")
    assert third.is_owned is False


async def test_react_is_unsupported(reddit_client):
    # Reddit reacting is voting — the adapter offers no such method.
    with pytest.raises(UnsupportedCapability):
        await _adapter(reddit_client).react(
            _session(), TargetRef(raw="t3_abc", resolved=True), "upvote", dry_run=False
        )
