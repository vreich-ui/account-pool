"""Exercise the MCP tool surface in-process, driving the full lifecycle + acting flow."""

from __future__ import annotations

import json

import pytest

from account_pool.server.mcp_server import build_mcp


async def call(mcp, name, **args):
    """Call a tool and return its structured payload (unwrapping list results)."""
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


async def test_contract_tool_and_resource(mcp):
    contract = await call(mcp, "account_contract", platform="reddit")
    assert contract["platform"] == "reddit"
    assert contract["boundaries"]["vote_manipulation"] == "hard-blocked"
    assert "not_authorized" in {d["code"] for d in contract["denial_codes"]}


async def test_full_lifecycle_and_acting_flow(mcp):
    agent = "agent-7"
    reg = await call(mcp, "account_register", platform="mastodon", handle="brandvoice", agent_name=agent)
    aid = reg["account_id"]

    await call(
        mcp,
        "account_authorize",
        account_id=aid,
        owner="kugelbrands",
        consent_scope=["publish", "comment", "read"],
        agent_name=agent,
        attested_by="human",
    )
    connected = await call(
        mcp,
        "account_connect",
        account_id=aid,
        auth_type="oauth2",
        credentials={"access_token": "z"},
        agent_name=agent,
    )
    assert connected["status"] == "active"
    assert connected["compliance"]["bot_flag_set"] is True

    checkout = await call(mcp, "account_checkout", account_id=aid, agent_name=agent)
    token = checkout["lock_token"]
    assert token

    draft = await call(mcp, "draft_create", account_id=aid, body="Launch day is here!")
    did = draft["draft_id"]

    v = await call(
        mcp,
        "action_validate",
        account_id=aid,
        action_type="publish",
        agent_name=agent,
        draft_id=did,
        lock_token=token,
    )
    assert v["outcome"] == "allow"

    pub = await call(mcp, "publish", account_id=aid, agent_name=agent, lock_token=token, draft_id=did)
    assert pub["state"] == "done"

    # third-party comment -> approval queue
    cdraft = await call(mcp, "draft_create", account_id=aid, body="Thanks for the mention!")
    com = await call(
        mcp,
        "comment",
        account_id=aid,
        agent_name=agent,
        lock_token=token,
        target="someone/status/9",
        draft_id=cdraft["draft_id"],
    )
    assert com["state"] == "needs_approval"
    approval_id = com["result"]["approval_id"]

    open_items = await call(mcp, "approvals_list")
    assert any(x["approval_id"] == approval_id for x in open_items)

    decided = await call(
        mcp, "approval_decide", approval_id=approval_id, decision="approve", decided_by="human-reviewer"
    )
    assert decided["action_state"] == "done"

    # audit shows activity for this account
    events = await call(mcp, "audit_query", account_id=aid)
    assert len(events) >= 4
    inv = await call(mcp, "account_inventory")
    assert inv["total"] == 1 and inv["by_status"]["active"] == 1


async def test_idempotency_key_dedupes_publish(mcp):
    agent = "agent-8"
    reg = await call(mcp, "account_register", platform="bluesky", handle="skybrand", agent_name=agent)
    aid = reg["account_id"]
    await call(
        mcp, "account_authorize", account_id=aid, owner="k", consent_scope=["publish"], agent_name=agent
    )
    await call(
        mcp,
        "account_connect",
        account_id=aid,
        auth_type="app_password",
        credentials={"pw": "x"},
        agent_name=agent,
    )
    checkout = await call(mcp, "account_checkout", account_id=aid, agent_name=agent)
    token = checkout["lock_token"]
    draft = await call(mcp, "draft_create", account_id=aid, body="Only once")

    first = await call(
        mcp,
        "publish",
        account_id=aid,
        agent_name=agent,
        lock_token=token,
        draft_id=draft["draft_id"],
        idempotency_key="k-123",
    )
    second = await call(
        mcp,
        "publish",
        account_id=aid,
        agent_name=agent,
        lock_token=token,
        draft_id=draft["draft_id"],
        idempotency_key="k-123",
    )
    assert first["action_id"] == second["action_id"]
