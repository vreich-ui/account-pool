"""End-to-end M1 flow: the RedditAdapter driven through the full service pipeline (fake client)."""

from __future__ import annotations


async def _active_reddit(app, handle: str = "brand_reddit"):
    acc = app.account_service
    a = acc.register("agent-1", "reddit", handle)
    acc.authorize(
        "agent-1",
        a.account_id,
        owner="kugelbrands",
        consent_scope=["publish", "comment", "read"],
        attested_by="human",
    )
    a = await acc.connect(
        "agent-1",
        a.account_id,
        "oauth2",
        {"username": handle, "client_id": "x", "client_secret": "y", "refresh_token": "z"},
    )
    return a


async def test_publish_to_profile_dry_run(reddit_app, reddit_client):
    a = await _active_reddit(reddit_app)
    assert a.status.value == "active"  # authenticated via fake client
    token = reddit_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = reddit_app.action_service.create_draft(a.account_id, "our update", title="Launch!")
    res = await reddit_app.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done"
    assert res.result["dry_run"] is True
    assert res.result["detail"]["subreddit"] == "u_brand_reddit"
    assert reddit_client.submitted == []  # dry-run: nothing really posted


async def test_publish_without_title_fails(reddit_app):
    a = await _active_reddit(reddit_app)
    token = reddit_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = reddit_app.action_service.create_draft(a.account_id, "body but no title")
    res = await reddit_app.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "failed"
    assert res.result["denial_code"] == "content_invalid"


async def test_third_party_comment_routes_then_executes(reddit_app, reddit_client):
    a = await _active_reddit(reddit_app)
    token = reddit_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = reddit_app.action_service.create_draft(a.account_id, "helpful reply")
    # Comment on someone else's submission -> approval queue.
    routed = await reddit_app.action_service.comment(
        "agent-1", a.account_id, token, "https://www.reddit.com/r/python/comments/abc123/x/", draft.draft_id
    )
    assert routed.state.value == "needs_approval"
    decided = await reddit_app.action_service.decide_approval(
        routed.result["approval_id"], "approve", decided_by="human"
    )
    assert decided["action_state"] == "done"


async def test_live_publish_reaches_client(reddit_app_live, reddit_client):
    a = await _active_reddit(reddit_app_live)
    token = reddit_app_live.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = reddit_app_live.action_service.create_draft(a.account_id, "real body", title="Real Title")
    res = await reddit_app_live.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done"
    assert len(reddit_client.submitted) == 1
    assert reddit_client.submitted[0].title == "Real Title"


async def test_reddit_read_and_search(reddit_app):
    a = await _active_reddit(reddit_app)
    read = await reddit_app.action_service.read("agent-1", a.account_id, "t3_abc123")
    assert read.state.value == "done"
    assert read.result["items"]
    search = await reddit_app.action_service.search("agent-1", a.account_id, "r/python praw")
    assert search.state.value == "done"
    assert search.result["detail"]["subreddit"] == "python"
