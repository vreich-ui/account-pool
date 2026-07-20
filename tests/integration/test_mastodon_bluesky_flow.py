"""M2 end-to-end: Mastodon + Bluesky adapters driven through the full service pipeline."""

from __future__ import annotations


async def _active(app, platform, handle, creds):
    acc = app.account_service
    a = acc.register("agent-1", platform, handle)
    acc.authorize(
        "agent-1",
        a.account_id,
        owner="kugelbrands",
        consent_scope=["publish", "comment", "react", "read"],
        attested_by="human",
    )
    return await acc.connect("agent-1", a.account_id, "oauth2", creds)


# ---- Mastodon ----
async def test_mastodon_connect_sets_bot_flag_and_publishes(mastodon_app, mastodon_client):
    a = await _active(
        mastodon_app, "mastodon", "brandmasto", {"access_token": "t", "api_base_url": "https://m.example"}
    )
    assert a.status.value == "active"
    assert a.compliance.bot_flag_set is True  # set during connect
    token = mastodon_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = mastodon_app.action_service.create_draft(a.account_id, "hello fediverse")
    res = await mastodon_app.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done" and res.result["dry_run"] is True


async def test_mastodon_third_party_comment_routes(mastodon_app):
    a = await _active(
        mastodon_app, "mastodon", "brandmasto", {"access_token": "t", "api_base_url": "https://m.example"}
    )
    token = mastodon_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = mastodon_app.action_service.create_draft(a.account_id, "reply")
    routed = await mastodon_app.action_service.comment(
        "agent-1", a.account_id, token, "https://m.example/@someone/555", draft.draft_id
    )
    assert routed.state.value == "needs_approval"


async def test_mastodon_live_publish_reaches_client(mastodon_app_live, mastodon_client):
    a = await _active(
        mastodon_app_live,
        "mastodon",
        "brandmasto",
        {"access_token": "t", "api_base_url": "https://m.example"},
    )
    token = mastodon_app_live.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = mastodon_app_live.action_service.create_draft(a.account_id, "real toot")
    res = await mastodon_app_live.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done"
    assert mastodon_client.posted[-1]["body"] == "real toot"


# ---- Bluesky ----
async def test_bluesky_connect_sets_self_label_and_publishes(bluesky_app, bluesky_client):
    a = await _active(
        bluesky_app,
        "bluesky",
        "brand.bsky.social",
        {"identifier": "brand.bsky.social", "app_password": "app-pw"},
    )
    assert a.status.value == "active"
    assert a.compliance.self_label == "automated"
    token = bluesky_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = bluesky_app.action_service.create_draft(a.account_id, "hello sky")
    res = await bluesky_app.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done" and res.result["dry_run"] is True


async def test_bluesky_live_publish_and_third_party_reply(bluesky_app_live, bluesky_client):
    a = await _active(
        bluesky_app_live,
        "bluesky",
        "brand.bsky.social",
        {"identifier": "brand.bsky.social", "app_password": "app-pw"},
    )
    token = bluesky_app_live.lock_service.checkout(a.account_id, "agent-1").lock.token
    draft = bluesky_app_live.action_service.create_draft(a.account_id, "real skeet")
    res = await bluesky_app_live.action_service.publish("agent-1", a.account_id, token, draft.draft_id)
    assert res.state.value == "done"
    assert bluesky_client.posts[-1]["text"] == "real skeet"

    # A third-party reply is queued, then approved and executed against the client.
    rdraft = bluesky_app_live.action_service.create_draft(a.account_id, "nice post")
    routed = await bluesky_app_live.action_service.comment(
        "agent-1", a.account_id, token, "at://did:plc:x/app.bsky.feed.post/abc", rdraft.draft_id
    )
    assert routed.state.value == "needs_approval"
    decided = await bluesky_app_live.action_service.decide_approval(
        routed.result["approval_id"], "approve", decided_by="human"
    )
    assert decided["action_state"] == "done"
    assert bluesky_client.posts[-1]["reply_to"] is not None
