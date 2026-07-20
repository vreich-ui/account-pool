"""Thin FastAPI admin/ops surface over the services — a human-facing complement to the MCP server.

Serves the ADHD-friendly dashboard (``/``) and a read-mostly JSON API (accounts, inventory,
platforms, audit) plus approval decisions, so a person can review the fleet and approve/reject
queued third-party acts without going through an agent. The JSON API is guarded by a bearer token
named by ``settings.admin_bearer_env`` (open in non-prod when unset, denied in prod); the page shell,
``/health`` and ``/config`` are unauthenticated so the UI can render its safe-mode banner first.
"""

from __future__ import annotations

import os
from typing import Any

from .. import __version__
from ..app import AppContext, build_app
from ..config import get_settings
from ..errors import Conflict, InvalidState, LockHeld, NotFound
from .mcp_server import _account_summary

_ERROR_STATUS: dict[type[Exception], int] = {
    NotFound: 404,
    LockHeld: 423,
    Conflict: 409,
    InvalidState: 409,
}


def _approval_view(app: AppContext, approval: Any) -> dict[str, Any]:
    """Enrich an approval with the platform/handle/verb/target and draft text for the UI card."""
    action = app.action_service.get_action(approval.action_id)
    platform: str | None = None
    handle: str | None = None
    try:
        account = app.account_service.get(approval.account_id)
        platform, handle = account.platform.value, account.handle
    except NotFound:
        pass
    draft = None
    if action and action.draft_id:
        d = app.action_service.get_draft(action.draft_id)
        if d is not None:
            draft = {"title": d.title, "body": d.body}
    return {
        **approval.model_dump(mode="json"),
        "expired": approval.is_expired(),
        "platform": platform,
        "handle": handle,
        "verb": action.type.value if action else None,
        "target": action.target.raw if action and action.target else None,
        "draft": draft,
    }


def build_admin_app(app: AppContext) -> Any:
    from fastapi import Body, Depends, FastAPI, Header, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse

    from ..support import platform_overview
    from .ui import render_page

    settings = app.settings
    api = FastAPI(title="account-pool admin", version=__version__)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        expected = os.environ.get(settings.admin_bearer_env)
        if expected:
            if authorization != f"Bearer {expected}":
                raise HTTPException(status_code=401, detail="invalid or missing bearer token")
            return
        if settings.is_prod:
            raise HTTPException(status_code=401, detail="admin bearer token not configured")

    auth = [Depends(require_auth)]

    @api.exception_handler(NotFound)
    @api.exception_handler(LockHeld)
    @api.exception_handler(Conflict)
    @api.exception_handler(InvalidState)
    async def _handle(_req: Any, exc: Exception) -> Any:
        status = _ERROR_STATUS.get(type(exc), 400)
        return JSONResponse(status_code=status, content={"error": type(exc).__name__, "message": str(exc)})

    # ---- page shell + unauthenticated status ----
    @api.get("/", response_class=HTMLResponse)
    @api.get("/ui", response_class=HTMLResponse)
    def dashboard() -> Any:
        return HTMLResponse(render_page())

    @api.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "environment": settings.environment}

    @api.get("/config")
    def config() -> dict[str, Any]:
        return {
            "environment": settings.environment,
            "dry_run": settings.dry_run,
            "server": settings.server_name,
            "auth_required": bool(os.environ.get(settings.admin_bearer_env)) or settings.is_prod,
        }

    # ---- authenticated JSON API ----
    @api.get("/accounts", dependencies=auth)
    def list_accounts(
        platform: str | None = None,
        status: str | None = None,
        pool: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        return [_account_summary(a) for a in app.account_service.list(platform, status, pool, tag)]

    @api.get("/accounts/{account_id}", dependencies=auth)
    def get_account(account_id: str) -> dict[str, Any]:
        return app.account_service.get(account_id).model_dump(mode="json")

    @api.get("/accounts/{account_id}/connection", dependencies=auth)
    def account_connection(account_id: str) -> dict[str, Any]:
        conn = app.account_service.get_connection(account_id)
        return conn.model_dump(mode="json") if conn else {"connection": None}

    # ---- account lifecycle (administration) ----
    @api.post("/accounts", dependencies=auth)
    async def create_account(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Register an account; optionally authorize and connect it in the same call."""
        acc_svc = app.account_service
        agent = body.get("agent_name", "admin")
        account = acc_svc.register(
            agent, body["platform"], body["handle"],
            display_name=body.get("display_name"), persona=body.get("persona"),
            pool=body.get("pool"), tags=body.get("tags"),
        )
        aid = account.account_id
        if body.get("authorize"):
            az = body["authorize"]
            account = acc_svc.authorize(
                agent, aid, owner=az["owner"], consent_scope=az["consent_scope"],
                evidence_ref=az.get("evidence_ref"), attested_by=az.get("attested_by"),
            )
        if body.get("connect"):
            cn = body["connect"]
            account = await acc_svc.connect(
                agent, aid, cn["auth_type"], cn.get("credentials", {}),
                scopes=cn.get("scopes"), provider=cn.get("provider"),
            )
        return account.model_dump(mode="json")

    @api.post("/accounts/{account_id}/authorize", dependencies=auth)
    def authorize(account_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        a = app.account_service.authorize(
            body.get("agent_name", "admin"), account_id, owner=body["owner"],
            consent_scope=body["consent_scope"], evidence_ref=body.get("evidence_ref"),
            attested_by=body.get("attested_by"),
        )
        return a.model_dump(mode="json")

    @api.post("/accounts/{account_id}/connect", dependencies=auth)
    async def connect(account_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        a = await app.account_service.connect(
            body.get("agent_name", "admin"), account_id, body["auth_type"],
            body.get("credentials", {}), scopes=body.get("scopes"), provider=body.get("provider"),
        )
        return a.model_dump(mode="json")

    @api.post("/accounts/{account_id}/refresh-credentials", dependencies=auth)
    async def refresh_credentials(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = await app.account_service.refresh_credentials(body.get("agent_name", "admin"), account_id)
        return a.model_dump(mode="json")

    @api.post("/accounts/{account_id}/health-check", dependencies=auth)
    async def account_health(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = await app.account_service.health_check(body.get("agent_name", "admin"), account_id)
        return {"account_id": a.account_id, "health": a.health.model_dump(mode="json")}

    @api.post("/accounts/{account_id}/checkout", dependencies=auth)
    def checkout(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = app.lock_service.checkout(
            account_id, body.get("agent_name", "admin"), body.get("ttl_seconds")
        )
        return {
            "account_id": a.account_id,
            "lock_token": a.lock.token if a.lock else None,
            "record_version": a.record_version,
            "expires_at": a.lock.expires_at.isoformat() if a.lock else None,
        }

    @api.post("/accounts/{account_id}/checkin", dependencies=auth)
    def checkin(account_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        a = app.lock_service.checkin(account_id, body.get("agent_name", "admin"), body["lock_token"])
        return {"account_id": a.account_id, "locked": False, "status": a.status.value}

    @api.patch("/accounts/{account_id}", dependencies=auth)
    def patch_account(account_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        a = app.account_service.patch(
            body.get("agent_name", "admin"), account_id, body["lock_token"],
            body["expected_record_version"], body["updates"],
        )
        return a.model_dump(mode="json")

    @api.post("/accounts/{account_id}/retire", dependencies=auth)
    def retire(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = app.account_service.retire(body.get("agent_name", "admin"), account_id, body.get("reason"))
        return {"account_id": a.account_id, "status": a.status.value}

    @api.post("/accounts/{account_id}/revoke", dependencies=auth)
    def revoke(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = app.account_service.revoke_authorization(
            body.get("agent_name", "admin"), account_id, body.get("reason")
        )
        return {"account_id": a.account_id, "status": a.status.value}

    @api.post("/accounts/{account_id}/disconnect", dependencies=auth)
    def disconnect(account_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        a = app.account_service.disconnect(body.get("agent_name", "admin"), account_id)
        return {"account_id": a.account_id, "status": a.status.value, "connection_id": None}

    @api.get("/inventory", dependencies=auth)
    def inventory() -> dict[str, Any]:
        accounts = app.account_service.list()
        by_status: dict[str, int] = {}
        by_platform: dict[str, int] = {}
        for a in accounts:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_platform[a.platform.value] = by_platform.get(a.platform.value, 0) + 1
        return {
            "total": len(accounts),
            "by_status": by_status,
            "by_platform": by_platform,
            "open_approvals": len(app.action_service.list_open_approvals()),
        }

    @api.get("/platforms", dependencies=auth)
    def platforms() -> list[dict[str, Any]]:
        return platform_overview()

    @api.get("/approvals", dependencies=auth)
    def list_approvals(platform: str | None = None, account_id: str | None = None) -> list[dict[str, Any]]:
        items = app.action_service.list_open_approvals(platform=platform, account_id=account_id)
        return [_approval_view(app, i) for i in items]

    @api.get("/approvals/{approval_id}", dependencies=auth)
    def get_approval(approval_id: str) -> dict[str, Any]:
        item = app.action_service.get_approval(approval_id)
        if item is None:
            raise NotFound(f"approval '{approval_id}' not found")
        return _approval_view(app, item)

    @api.post("/approvals/{approval_id}/decide", dependencies=auth)
    async def decide(approval_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return await app.action_service.decide_approval(
            approval_id,
            decision=body["decision"],
            decided_by=body.get("decided_by", "admin"),
            reason=body.get("reason"),
        )

    @api.post("/approvals/{approval_id}/resubmit", dependencies=auth)
    async def resubmit(approval_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        return await app.action_service.resubmit_approval(body.get("caller", "admin"), approval_id)

    @api.get("/audit", dependencies=auth)
    def audit(
        account_id: str | None = None,
        action_id: str | None = None,
        verb: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = app.audit.query(account_id=account_id, action_id=action_id, verb=verb, limit=limit)
        return [e.model_dump(mode="json") for e in events]

    return api


def main() -> None:  # pragma: no cover
    """CLI entrypoint (``account-pool-admin``)."""
    import uvicorn

    settings = get_settings()
    app = build_app(settings)
    uvicorn.run(build_admin_app(app), host=settings.admin_host, port=settings.admin_port)


if __name__ == "__main__":  # pragma: no cover
    main()
