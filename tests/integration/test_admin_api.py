"""The FastAPI admin surface (driven with Starlette's TestClient)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from account_pool.server.rest_admin import build_admin_app


def _setup_approval(app, make_active):
    async def _go():
        a = await make_active(app, platform="mastodon", handle="brand")
        token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
        d = app.action_service.create_draft(a.account_id, "helpful reply")
        routed = await app.action_service.comment(
            "agent-1", a.account_id, token, "someone/status/9", d.draft_id
        )
        return a, routed.result["approval_id"]

    return asyncio.run(_go())


def test_admin_read_and_approve(app, make_active):
    account, approval_id = _setup_approval(app, make_active)
    client = TestClient(build_admin_app(app))

    assert client.get("/health").json()["status"] == "ok"

    accounts = client.get("/accounts").json()
    assert any(x["account_id"] == account.account_id for x in accounts)

    inventory = client.get("/inventory").json()
    assert inventory["open_approvals"] == 1

    approvals = client.get("/approvals").json()
    assert approvals[0]["approval_id"] == approval_id
    assert approvals[0]["expired"] is False

    decided = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "approve", "decided_by": "human"},
    ).json()
    assert decided["action_state"] == "done"

    audit = client.get("/audit", params={"account_id": account.account_id}).json()
    assert len(audit) >= 1


def test_admin_not_found_maps_to_404(app):
    client = TestClient(build_admin_app(app))
    assert client.get("/accounts/does-not-exist").status_code == 404


def test_admin_bearer_auth(app, make_active, monkeypatch):
    _setup_approval(app, make_active)
    monkeypatch.setenv("ACCOUNT_POOL_ADMIN_BEARER", "s3cret")
    client = TestClient(build_admin_app(app))

    assert client.get("/health").status_code == 200  # health is unauthenticated
    assert client.get("/accounts").status_code == 401  # missing token
    ok = client.get("/accounts", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
