"""Thin FastAPI admin/ops surface over the services — a human-facing complement to the MCP server.

Read-mostly, plus approval decisions, so a person can review the fleet and approve/reject queued
third-party acts without going through an agent. Guarded by a bearer token named by
``settings.admin_bearer_env``; if that env var is unset the surface is open only in non-prod (dev
convenience) and denies all requests in prod.
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


def build_admin_app(app: AppContext) -> Any:
    from fastapi import Body, Depends, FastAPI, Header, HTTPException
    from fastapi.responses import JSONResponse

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

    @api.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "environment": settings.environment}

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

    @api.get("/approvals", dependencies=auth)
    def list_approvals(platform: str | None = None, account_id: str | None = None) -> list[dict[str, Any]]:
        items = app.action_service.list_open_approvals(platform=platform, account_id=account_id)
        return [{**i.model_dump(mode="json"), "expired": i.is_expired()} for i in items]

    @api.get("/approvals/{approval_id}", dependencies=auth)
    def get_approval(approval_id: str) -> dict[str, Any]:
        item = app.action_service.get_approval(approval_id)
        if item is None:
            raise NotFound(f"approval '{approval_id}' not found")
        return {**item.model_dump(mode="json"), "expired": item.is_expired()}

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
