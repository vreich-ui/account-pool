"""M4 approval polish: notification hook, expiry, and resubmit."""

from __future__ import annotations

from datetime import timedelta

from account_pool import clock
from account_pool.app import build_app
from account_pool.config import Settings


def _app(master_key, notifier=None):
    return build_app(
        Settings(database_url="sqlite:///:memory:", dry_run=True, environment="dev"),
        notifier=notifier,
    )


async def _routed_approval(app, make_active):
    a = await make_active(app, platform="mastodon", handle="brand")
    token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = app.action_service.create_draft(a.account_id, "reply")
    routed = await app.action_service.comment("agent-1", a.account_id, token, "someone/status/9", d.draft_id)
    return a, routed.result["approval_id"]


async def test_notifier_fires_on_approval(master_key, make_active):
    calls = []
    app = _app(master_key, notifier=lambda approval, account: calls.append(approval.approval_id))
    _, approval_id = await _routed_approval(app, make_active)
    assert calls == [approval_id]


async def test_expired_approval_cannot_be_approved(master_key, make_active):
    app = _app(master_key)
    _, approval_id = await _routed_approval(app, make_active)
    # Age the approval past its TTL.
    appr = app.approvals.get(approval_id)
    appr.expires_at = clock.now() - timedelta(seconds=1)
    app.approvals._repo.upsert(appr)

    result = await app.action_service.decide_approval(approval_id, "approve", decided_by="human")
    assert result["action_state"] == "refused"
    assert result["denial_code"] == "approval_stale"


async def test_resubmit_reopens_for_review(master_key, make_active):
    app = _app(master_key)
    _, approval_id = await _routed_approval(app, make_active)
    # Reviewer asks for changes.
    await app.action_service.decide_approval(approval_id, "request_changes", "human", "tone")
    assert app.approvals.get(approval_id).review_state.value == "changes_requested"
    # Agent resubmits -> back to open.
    out = await app.action_service.resubmit_approval("agent-1", approval_id)
    assert out["review_state"] == "open"
    assert app.approvals.get(approval_id).review_state.value == "open"
