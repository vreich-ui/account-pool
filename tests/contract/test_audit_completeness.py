"""Every acting path must emit an audit event: executed, refused, AND approved."""

from __future__ import annotations

from account_pool.domain.enums import DecisionOutcome


async def test_every_action_is_audited(app, make_active):
    a = await make_active(app, platform="mastodon", handle="auditbrand")
    svc = app.action_service
    locked = app.lock_service.checkout(a.account_id, "agent-1")
    token = locked.lock.token

    # executed publish
    d1 = svc.create_draft(a.account_id, "own channel post")
    published = await svc.publish("agent-1", a.account_id, token, d1.draft_id)

    # refused: vote react is hard-blocked
    refused = await svc.react("agent-1", a.account_id, token, "someone/post", "upvote")

    # routed then approved
    d2 = svc.create_draft(a.account_id, "reply to a thread")
    routed = await svc.comment("agent-1", a.account_id, token, "someone/post", d2.draft_id)
    decided = await svc.decide_approval(routed.result["approval_id"], "approve", "human")

    # Each action id has at least one audit event.
    for action_id in (published.action_id, refused.action_id, routed.action_id):
        assert app.audit.query(action_id=action_id), f"no audit for {action_id}"

    # The refusal is recorded as a DENY.
    refused_events = app.audit.query(action_id=refused.action_id)
    assert refused_events[0].outcome == DecisionOutcome.DENY

    # The routed comment produced a ROUTE event and, after approval, an ALLOW event.
    routed_events = app.audit.query(action_id=routed.action_id)
    outcomes = {e.outcome for e in routed_events}
    assert DecisionOutcome.ROUTE_TO_APPROVAL in outcomes
    assert DecisionOutcome.ALLOW in outcomes
    assert decided["action_state"] == "done"


async def test_refused_action_has_decision_trace(app, make_active):
    a = await make_active(app, platform="reddit", handle="tracebrand")
    svc = app.action_service
    token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
    refused = await svc.react("agent-1", a.account_id, token, "r/x/post", "upvote")
    assert refused.state.value == "refused"
    # The trace explains which guard stopped it.
    guards = {step.guard for step in refused.decision_trace}
    assert "capability" in guards or "manipulation" in guards
