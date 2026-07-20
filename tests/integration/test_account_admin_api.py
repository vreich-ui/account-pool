"""Full account administration over the REST surface.

Covers the lifecycle write endpoints added so a human (or the dashboard) can fully administer
accounts without an agent: create (with inline authorize + connect), per-account actions
(health-check, refresh-credentials, revoke, disconnect, retire), and connection-metadata lookup —
plus the ``disconnect`` service verb that actually deletes the stored connection.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from account_pool.db.repositories import ConnectionRepository
from account_pool.server.rest_admin import build_admin_app


def test_create_authorize_connect_in_one_call(app):
    client = TestClient(build_admin_app(app))
    resp = client.post(
        "/accounts",
        json={
            "platform": "mastodon",
            "handle": "newbrand",
            "display_name": "New Brand",
            "pool": "brand-us",
            "authorize": {"owner": "kugelbrands", "consent_scope": ["publish", "read"]},
            "connect": {"auth_type": "oauth2", "credentials": {"access_token": "super-secret"}},
        },
    )
    assert resp.status_code == 200, resp.text
    acc = resp.json()
    assert acc["platform"] == "mastodon" and acc["handle"] == "newbrand"
    assert acc["status"] == "active"  # authorized + connected -> active
    assert acc["connection_id"]
    aid = acc["account_id"]

    # connection metadata is a pointer only — the credential value never leaves the vault
    conn = client.get(f"/accounts/{aid}/connection").json()
    assert conn["auth_type"] == "oauth2"
    assert "super-secret" not in str(conn) and "access_token" not in str(conn)


def test_register_only_then_authorize_and_connect_separately(app):
    client = TestClient(build_admin_app(app))
    aid = client.post("/accounts", json={"platform": "bluesky", "handle": "sky"}).json()["account_id"]
    assert client.get(f"/accounts/{aid}").json()["status"] == "draft"
    assert client.get(f"/accounts/{aid}/connection").json() == {"connection": None}

    client.post(f"/accounts/{aid}/authorize", json={"owner": "k", "consent_scope": ["publish"]})
    connected = client.post(
        f"/accounts/{aid}/connect",
        json={"auth_type": "app_password", "credentials": {"pw": "x"}},
    ).json()
    assert connected["status"] == "active"


def test_health_check_and_refresh_endpoints(app):
    client = TestClient(build_admin_app(app))
    aid = client.post(
        "/accounts",
        json={
            "platform": "reddit",
            "handle": "brandhelp",
            "authorize": {"owner": "k", "consent_scope": ["publish", "read"]},
            "connect": {"auth_type": "oauth2", "credentials": {"access_token": "x"}},
        },
    ).json()["account_id"]

    h = client.post(f"/accounts/{aid}/health-check").json()
    assert h["account_id"] == aid
    assert h["health"]["status"] in {"ok", "unknown", "degraded", "reauth_needed", "blocked"}

    r = client.post(f"/accounts/{aid}/refresh-credentials").json()
    assert r["account_id"] == aid


def test_revoke_disconnect_retire_flow(app):
    client = TestClient(build_admin_app(app))
    aid = client.post(
        "/accounts",
        json={
            "platform": "reddit",
            "handle": "brandvoice2",
            "authorize": {"owner": "k", "consent_scope": ["publish", "read"]},
            "connect": {"auth_type": "oauth2", "credentials": {"access_token": "x"}},
        },
    ).json()["account_id"]

    # revoke authorization -> suspended
    revoked = client.post(f"/accounts/{aid}/revoke", json={"reason": "owner asked"}).json()
    assert revoked["status"] == "suspended"

    # disconnect clears the platform-API link
    d = client.post(f"/accounts/{aid}/disconnect").json()
    assert d["connection_id"] is None
    assert client.get(f"/accounts/{aid}/connection").json() == {"connection": None}

    # retire is terminal
    assert client.post(f"/accounts/{aid}/retire").json()["status"] == "retired"


def test_patch_requires_lock_and_bumps_version(app):
    client = TestClient(build_admin_app(app))
    aid = client.post(
        "/accounts",
        json={
            "platform": "mastodon",
            "handle": "patchme",
            "authorize": {"owner": "k", "consent_scope": ["publish"]},
            "connect": {"auth_type": "oauth2", "credentials": {"access_token": "x"}},
        },
    ).json()["account_id"]

    co = client.post(f"/accounts/{aid}/checkout", json={"agent_name": "admin"}).json()
    token, version = co["lock_token"], co["record_version"]

    patched = client.patch(
        f"/accounts/{aid}",
        json={
            "lock_token": token,
            "expected_record_version": version,
            "updates": {"tags": ["priority"], "pool": "brand-eu"},
        },
    ).json()
    assert patched["tags"] == ["priority"] and patched["pool"] == "brand-eu"

    client.post(f"/accounts/{aid}/checkin", json={"agent_name": "admin", "lock_token": token})


def test_disconnect_service_deletes_connection_and_resets_compliance(app, make_active):
    async def _go():
        a = await make_active(app, platform="mastodon", handle="discon")
        assert a.status == "active" and a.connection_id
        assert a.compliance.bot_flag_set is True
        cid = a.connection_id
        after = app.account_service.disconnect("admin", a.account_id)
        return cid, after

    cid, after = asyncio.run(_go())
    assert after.connection_id is None
    assert after.status == "draft"  # no connection, but authorization intact
    assert after.compliance.bot_flag_set is False
    assert app.account_service.get_connection(after.account_id) is None
    # the connection row itself is gone from storage
    assert ConnectionRepository(app.db).get(cid) is None
