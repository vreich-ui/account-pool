"""The MCP admin surface: an external agent can fully administer accounts and inspect platform-API
coverage through tools alone — revoke, disconnect, read connection metadata, list platform tiers."""

from __future__ import annotations

import json

import pytest

from account_pool.server.mcp_server import build_mcp


async def call(mcp, name, **args):
    result = await mcp.call_tool(name, args)
    content, structured = result if isinstance(result, tuple) else (result, None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    return json.loads(content[0].text)


@pytest.fixture
def mcp(app):
    return build_mcp(app)


async def test_admin_tools_are_exposed(mcp):
    names = {t.name for t in await mcp.list_tools()}
    # the full administration surface is reachable by agents, not only the human REST app
    assert {"account_revoke", "account_disconnect", "account_connection", "platforms"} <= names


async def _make_active(mcp, platform="mastodon", handle="brand", agent="agent-1"):
    reg = await call(mcp, "account_register", platform=platform, handle=handle, agent_name=agent)
    aid = reg["account_id"]
    await call(
        mcp, "account_authorize", account_id=aid, owner="k",
        consent_scope=["publish", "read"], agent_name=agent, attested_by="human",
    )
    await call(
        mcp, "account_connect", account_id=aid, auth_type="oauth2",
        credentials={"access_token": "secret-value"}, agent_name=agent,
    )
    return aid


async def test_connection_metadata_has_no_secret(mcp):
    aid = await _make_active(mcp)
    conn = await call(mcp, "account_connection", account_id=aid)
    assert conn["auth_type"] == "oauth2"
    assert conn["account_id"] == aid
    # only a reference is exposed — never the credential value itself
    assert "secret-value" not in json.dumps(conn)


async def test_connection_absent_before_connect(mcp):
    reg = await call(mcp, "account_register", platform="bluesky", handle="sky", agent_name="a")
    assert await call(mcp, "account_connection", account_id=reg["account_id"]) == {"connection": None}


async def test_revoke_then_disconnect(mcp):
    aid = await _make_active(mcp, platform="reddit", handle="brandhelp")

    revoked = await call(mcp, "account_revoke", account_id=aid, agent_name="admin", reason="owner asked")
    assert revoked["status"] == "suspended"

    disc = await call(mcp, "account_disconnect", account_id=aid, agent_name="admin")
    assert disc["connection_id"] is None
    assert await call(mcp, "account_connection", account_id=aid) == {"connection": None}


async def test_platforms_tool_lists_every_platform_with_tier(mcp):
    from account_pool.domain.enums import Platform

    rows = await call(mcp, "platforms")
    assert len(rows) == len(list(Platform))
    assert all({"platform", "tier", "publish_mode", "verbs"} <= set(r) for r in rows)
    tiers = {r["tier"] for r in rows}
    assert {"live", "draft_only", "manual", "planned"} & tiers
