"""FastMCP server exposing the account pool to external agents.

Tools are mutations; resources are read-first reflection. Verbs mirror the object/checkout/review
vocabulary of the other MCP servers in this environment. Start with ``account_contract`` (or the
``contract://account/{platform}`` resource) to discover the schema, allowed verbs, and denial codes.

Note: expected control-flow errors (not found, lock held, conflict) propagate as MCP tool errors;
policy *refusals* come back as normal results — an action with ``state="refused"`` and a decision
trace — so an agent can inspect why.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..app import AppContext, build_app
from ..config import get_settings
from ..domain.contracts import build_account_contract
from ..domain.enums import Platform
from ..domain.models import Account
from ..policy.policies import get_platform_policy
from .context import normalize_agent


def _account_summary(a: Account) -> dict[str, Any]:
    return {
        "account_id": a.account_id,
        "platform": a.platform.value,
        "handle": a.handle,
        "status": a.status.value,
        "health": a.health.status.value,
        "requires_approval": a.requires_approval,
        "record_version": a.record_version,
        "locked_by": a.lock.holder if (a.lock and a.lock.is_active()) else None,
        "tags": a.tags,
        "pool": a.pool,
    }


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def build_mcp(app: AppContext) -> FastMCP:
    settings = app.settings
    mcp = FastMCP(settings.server_name, host=settings.mcp_host, port=settings.mcp_port)

    accounts = app.account_service
    actions = app.action_service
    locks = app.lock_service
    audit = app.audit
    approvals = app.approvals

    # ================= Account lifecycle ("acted upon") =================
    @mcp.tool()
    def account_contract(platform: str) -> dict[str, Any]:
        """Read-first: schema, capabilities, allowed verbs, policy, and denial codes for a platform."""
        plat = Platform(platform)
        caps = app.registry.get(plat).capabilities()
        return build_account_contract(caps, get_platform_policy(plat))

    @mcp.tool()
    def account_register(
        platform: str,
        handle: str,
        agent_name: str,
        display_name: str | None = None,
        persona: dict[str, Any] | None = None,
        pool: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Mint an Account object for a handle you own. Does not connect or authorize it yet."""
        a = accounts.register(
            normalize_agent(agent_name),
            platform,
            handle,
            display_name=display_name,
            persona=persona,
            pool=pool,
            tags=tags,
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    def account_authorize(
        account_id: str,
        owner: str,
        consent_scope: list[str],
        agent_name: str,
        evidence_ref: str | None = None,
        attested_by: str | None = None,
    ) -> dict[str, Any]:
        """Record consent to operate this account. This is the master gate — no acting without it."""
        a = accounts.authorize(
            normalize_agent(agent_name),
            account_id,
            owner,
            consent_scope,
            evidence_ref=evidence_ref,
            attested_by=attested_by,
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def account_connect(
        account_id: str,
        auth_type: str,
        credentials: dict[str, Any],
        agent_name: str,
        scopes: list[str] | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Store credentials in the encrypted vault, authenticate, and self-identify (bot flag /
        self-label). Credentials are held by reference; only a secret_ref is persisted in metadata."""
        a = await accounts.connect(
            normalize_agent(agent_name),
            account_id,
            auth_type,
            credentials,
            scopes=scopes,
            provider=provider,
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def account_refresh_credentials(account_id: str, agent_name: str) -> dict[str, Any]:
        """Refresh/rotate this account's stored credentials via the platform adapter."""
        a = await accounts.refresh_credentials(normalize_agent(agent_name), account_id)
        return a.model_dump(mode="json")

    @mcp.tool()
    def account_list(
        platform: str | None = None,
        status: str | None = None,
        pool: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """List account summaries, optionally filtered by platform/status/pool/tag."""
        return [_account_summary(a) for a in accounts.list(platform, status, pool, tag)]

    @mcp.tool()
    def account_get(account_id: str) -> dict[str, Any]:
        """Full detail for one account."""
        return accounts.get(account_id).model_dump(mode="json")

    @mcp.tool()
    def account_inventory() -> dict[str, Any]:
        """Fleet overview: counts by status/platform, locked accounts, and open approvals."""
        all_accounts = accounts.list()
        by_status: dict[str, int] = {}
        by_platform: dict[str, int] = {}
        locked = []
        for a in all_accounts:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_platform[a.platform.value] = by_platform.get(a.platform.value, 0) + 1
            if a.lock and a.lock.is_active():
                locked.append({"account_id": a.account_id, "holder": a.lock.holder})
        return {
            "total": len(all_accounts),
            "by_status": by_status,
            "by_platform": by_platform,
            "locked": locked,
            "open_approvals": len(approvals.list_open()),
        }

    @mcp.tool()
    def account_checkout(account_id: str, agent_name: str, ttl_seconds: int | None = None) -> dict[str, Any]:
        """Acquire the checkout lock (required before writing). Returns the lock_token."""
        a = locks.checkout(account_id, normalize_agent(agent_name), ttl_seconds)
        return {
            "account_id": a.account_id,
            "lock_token": a.lock.token if a.lock else None,
            "expires_at": a.lock.expires_at.isoformat() if a.lock else None,
            "record_version": a.record_version,
        }

    @mcp.tool()
    def account_refresh_lock(
        account_id: str, agent_name: str, lock_token: str, ttl_seconds: int | None = None
    ) -> dict[str, Any]:
        """Extend an active checkout lease."""
        a = locks.refresh(account_id, normalize_agent(agent_name), lock_token, ttl_seconds)
        return {"account_id": a.account_id, "expires_at": a.lock.expires_at.isoformat() if a.lock else None}

    @mcp.tool()
    def account_checkin(account_id: str, agent_name: str, lock_token: str) -> dict[str, Any]:
        """Release the checkout lock."""
        a = locks.checkin(account_id, normalize_agent(agent_name), lock_token)
        return {"account_id": a.account_id, "status": a.status.value, "locked": False}

    @mcp.tool()
    def account_patch(
        account_id: str,
        agent_name: str,
        lock_token: str,
        expected_record_version: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update persona/tags/pool/policy_overrides/requires_approval/status under lock + version."""
        a = accounts.patch(
            normalize_agent(agent_name), account_id, lock_token, expected_record_version, updates
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def account_health_check(account_id: str, agent_name: str) -> dict[str, Any]:
        """Run the adapter health-check and update health + compliance state."""
        a = await accounts.health_check(normalize_agent(agent_name), account_id)
        return {"account_id": a.account_id, "health": a.health.model_dump(mode="json")}

    @mcp.tool()
    def account_retire(account_id: str, agent_name: str, reason: str | None = None) -> dict[str, Any]:
        """Soft-retire an account (no further acting)."""
        a = accounts.retire(normalize_agent(agent_name), account_id, reason)
        return {"account_id": a.account_id, "status": a.status.value}

    # ================= Acting ("acts") =================
    @mcp.tool()
    def draft_create(
        account_id: str,
        body: str,
        title: str | None = None,
        media_refs: list[str] | None = None,
        disclosure: str | None = None,
    ) -> dict[str, Any]:
        """Create a content draft. Always allowed — drafting has no side effects. ``title`` is
        required by some platforms (Reddit submissions, Medium posts)."""
        return actions.create_draft(account_id, body, title, media_refs, disclosure).model_dump(mode="json")

    @mcp.tool()
    def draft_update(
        draft_id: str,
        body: str | None = None,
        title: str | None = None,
        media_refs: list[str] | None = None,
        disclosure: str | None = None,
    ) -> dict[str, Any]:
        """Revise a draft (bumps its revision, invalidating any pinned approval)."""
        return actions.update_draft(draft_id, body, title, media_refs, disclosure).model_dump(mode="json")

    @mcp.tool()
    async def action_validate(
        account_id: str,
        action_type: str,
        agent_name: str,
        draft_id: str | None = None,
        target: str | None = None,
        react_kind: str | None = None,
        lock_token: str | None = None,
    ) -> dict[str, Any]:
        """Dry-run the policy guard for a would-be action (no execution, no audit). Like object_validate."""
        return await actions.validate(
            normalize_agent(agent_name),
            account_id,
            action_type,
            draft_id=draft_id,
            target_raw=target,
            react_kind=react_kind,
            lock_token=lock_token,
        )

    @mcp.tool()
    async def publish(
        account_id: str,
        agent_name: str,
        lock_token: str,
        draft_id: str,
        idempotency_key: str | None = None,
        scheduled_for: str | None = None,
    ) -> dict[str, Any]:
        """Publish a draft to the account's OWN channel (may auto-execute under hybrid autonomy)."""
        a = await actions.publish(
            normalize_agent(agent_name),
            account_id,
            lock_token,
            draft_id,
            idempotency_key=idempotency_key,
            scheduled_for=_parse_dt(scheduled_for),
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def comment(
        account_id: str,
        agent_name: str,
        lock_token: str,
        target: str,
        draft_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Comment/reply on a target. Third-party targets route to the approval queue by default."""
        a = await actions.comment(
            normalize_agent(agent_name),
            account_id,
            lock_token,
            target,
            draft_id,
            idempotency_key=idempotency_key,
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def react(
        account_id: str,
        agent_name: str,
        lock_token: str,
        target: str,
        kind: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Like/boost a target (capability + policy gated). Voting is hard-blocked."""
        a = await actions.react(
            normalize_agent(agent_name),
            account_id,
            lock_token,
            target,
            kind,
            idempotency_key=idempotency_key,
        )
        return a.model_dump(mode="json")

    @mcp.tool()
    async def read(account_id: str, agent_name: str, target: str) -> dict[str, Any]:
        """Read a specific item/thread (read-only, no lock required)."""
        a = await actions.read(normalize_agent(agent_name), account_id, target)
        return a.model_dump(mode="json")

    @mcp.tool()
    async def monitor(account_id: str, agent_name: str, query: str, limit: int = 25) -> dict[str, Any]:
        """Monitor/search a query or feed (read-only)."""
        a = await actions.search(normalize_agent(agent_name), account_id, query, limit=limit)
        return a.model_dump(mode="json")

    # ================= Approvals =================
    @mcp.tool()
    def approvals_list() -> list[dict[str, Any]]:
        """List open approval items awaiting a human decision."""
        return [x.model_dump(mode="json") for x in approvals.list_open()]

    @mcp.tool()
    def approval_get(approval_id: str) -> dict[str, Any]:
        """Full detail for one approval item, including its pinned draft revision."""
        item = approvals.get(approval_id)
        if item is None:
            return {"error": "NotFound", "message": f"approval '{approval_id}' not found"}
        return item.model_dump(mode="json")

    @mcp.tool()
    async def approval_decide(
        approval_id: str, decision: str, decided_by: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Decide an approval: 'approve' (executes), 'reject', or 'request_changes'."""
        return await actions.decide_approval(approval_id, decision, decided_by, reason)

    # ================= Observability =================
    @mcp.tool()
    def audit_query(
        account_id: str | None = None,
        action_id: str | None = None,
        verb: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query the append-only audit log."""
        return [e.model_dump(mode="json") for e in audit.query(account_id, action_id, verb, limit)]

    @mcp.tool()
    async def policy_explain(
        account_id: str,
        verb: str,
        agent_name: str = "anonymous-agent",
        target: str | None = None,
        draft_id: str | None = None,
        react_kind: str | None = None,
        lock_token: str | None = None,
    ) -> dict[str, Any]:
        """Explain whether/why a verb would be allowed, denied, or routed to approval (no side effects)."""
        return await actions.validate(
            normalize_agent(agent_name),
            account_id,
            verb,
            draft_id=draft_id,
            target_raw=target,
            react_kind=react_kind,
            lock_token=lock_token,
        )

    # ================= Resources (read-first reflection) =================
    @mcp.resource("contract://account/{platform}")
    def contract_resource(platform: str) -> str:
        plat = Platform(platform)
        caps = app.registry.get(plat).capabilities()
        return json.dumps(build_account_contract(caps, get_platform_policy(plat)), indent=2)

    @mcp.resource("account://{account_id}")
    def account_resource(account_id: str) -> str:
        return accounts.get(account_id).model_dump_json(indent=2)

    @mcp.resource("inventory://accounts")
    def inventory_resource() -> str:
        return json.dumps(account_inventory(), indent=2)

    @mcp.resource("approvals://open")
    def approvals_resource() -> str:
        return json.dumps([x.model_dump(mode="json") for x in approvals.list_open()], indent=2)

    return mcp


# Module-level singleton for the CLI entrypoint.
_app: AppContext | None = None


def main() -> None:
    """CLI entrypoint (``account-pool-mcp``)."""
    global _app
    settings = get_settings()
    _app = build_app(settings)
    mcp = build_mcp(_app)
    if settings.mcp_transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
