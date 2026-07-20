"""M3 end-to-end: TwitterAdapter driven through the full service pipeline."""

from __future__ import annotations


async def _active(app, handle="brandx"):
    acc = app.account_service
    a = acc.register("agent-1", "twitter", handle)
    acc.authorize(
        "agent-1",
        a.account_id,
        owner="kugelbrands",
        consent_scope=["publish", "comment", "react", "read"],
        attested_by="human",
    )
    return await acc.connect("agent-1", a.account_id, "oauth2", {"bearer_token": "b"})


async def test_publish_dry_run(twitter_app, twitter_client):
    a = await _active(twitter_app)
    assert a.status.value == "active"
    token = twitter_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = twitter_app.action_service.create_draft(a.account_id, "hello X")
    res = await twitter_app.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done" and res.result["dry_run"] is True
    assert twitter_client.tweets == []


async def test_live_publish_and_third_party_reply(twitter_app_live, twitter_client):
    a = await _active(twitter_app_live)
    token = twitter_app_live.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = twitter_app_live.action_service.create_draft(a.account_id, "real tweet")
    res = await twitter_app_live.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done"
    assert twitter_client.tweets[-1]["text"] == "real tweet"

    rdraft = twitter_app_live.action_service.create_draft(a.account_id, "good take")
    routed = await twitter_app_live.action_service.comment(
        "agent-1", a.account_id, token, "https://x.com/someone/status/999", rdraft.draft_id
    )
    assert routed.state.value == "needs_approval"
    decided = await twitter_app_live.action_service.decide_approval(
        routed.result["approval_id"], "approve", decided_by="human"
    )
    assert decided["action_state"] == "done"
    assert twitter_client.tweets[-1]["reply_to"] == "999"
