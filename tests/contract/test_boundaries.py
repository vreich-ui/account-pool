"""The non-negotiable boundaries — several enforced by *absence of capability*."""

from __future__ import annotations

from account_pool.adapters.base import PlatformAdapter
from account_pool.domain.enums import DenialCode, LifecycleState, Platform
from account_pool.server.mcp_server import build_mcp


async def test_no_scrape_or_account_generation_surface(app):
    # The adapter contract has no scraping / fabrication method.
    methods = [m.lower() for m in dir(PlatformAdapter)]
    assert not any("scrap" in m for m in methods)
    assert not any("generate" in m and "credential" not in m for m in methods)

    # The MCP surface exposes no account-fabrication or scraping tool.
    mcp = build_mcp(app)
    names = {t.name for t in await mcp.list_tools()}
    assert not any(("scrap" in n) or ("generat" in n) for n in names)
    assert "account_register" in names  # registration exists — but requires an ownership attestation


async def test_cannot_act_on_unauthorized_account(app):
    """Without authorization, connect leaves the account non-active and acting is refused."""
    acc = app.account_service
    a = acc.register("agent-1", "mastodon", "unauth")
    a = await acc.connect("agent-1", a.account_id, "oauth2", {"access_token": "x"})
    assert a.status == LifecycleState.CONNECTED  # not ACTIVE without authorization

    token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = app.action_service.create_draft(a.account_id, "should not post")
    result = await app.action_service.publish("agent-1", a.account_id, token, d.draft_id)
    assert result.state.value == "refused"
    assert result.decision_trace[-1].denial_code == DenialCode.ACCOUNT_NOT_ACTIVE


async def test_substack_is_manual_only(app):
    acc = app.account_service
    a = acc.register("agent-1", "substack", "brandletter")
    acc.authorize("agent-1", a.account_id, owner="k", consent_scope=["publish"])
    a = await acc.connect("agent-1", a.account_id, "api_key", {"key": "x"})
    token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = app.action_service.create_draft(a.account_id, "newsletter body")
    result = await app.action_service.publish("agent-1", a.account_id, token, d.draft_id)
    assert result.state.value == "refused"
    assert result.decision_trace[-1].denial_code == DenialCode.PUBLISH_MODE_MANUAL


async def test_medium_is_draft_only_no_real_write(app_live):
    """Medium stages a draft instead of publishing — even with dry_run off, nothing is written."""
    acc = app_live.account_service
    a = acc.register("agent-1", "medium", "brandmedium")
    acc.authorize("agent-1", a.account_id, owner="k", consent_scope=["publish"])
    a = await acc.connect("agent-1", a.account_id, "oauth2", {"token": "x"})
    token = app_live.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = app_live.action_service.create_draft(a.account_id, "article body")
    result = await app_live.action_service.publish("agent-1", a.account_id, token, d.draft_id)
    assert result.state.value == "done"
    assert result.result["detail"]["staged"] is True
    # The Medium adapter never received a real publish call.
    fake = app_live.registry.get(Platform.MEDIUM)
    assert len(fake.published) == 0
