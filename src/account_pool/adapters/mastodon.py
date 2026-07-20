"""Mastodon adapter (Mastodon.py).

Mastodon.py is synchronous (requests-based), so every SDK call is dispatched to a worker thread via
``anyio.to_thread`` to keep the MCP event loop responsive. ``publish`` posts a status to the
account's own timeline (own channel); ``comment`` replies to a status; ``react`` favourites or boosts.
Self-identification is real: ``ensure_self_identification`` sets the account's **bot flag**, which the
policy pipeline requires before this account may write.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial
from typing import Any

from anyio import to_thread

from ..domain.enums import HealthStatus, Platform, PublishMode
from ..domain.models import Capabilities, ContentDraft, TargetRef
from .base import (
    ActionResult,
    AdapterSession,
    AuthState,
    ComplianceState,
    HealthReport,
    PlatformAdapter,
    ReadResult,
    RefreshResult,
    SearchResult,
)

ClientFactory = Callable[[dict[str, Any]], Any]

_BOOST_KINDS = {"boost", "reblog", "repost"}


def _default_client_factory(credentials: dict[str, Any]) -> Any:
    from mastodon import Mastodon  # optional dependency

    return Mastodon(
        access_token=credentials.get("access_token"),
        api_base_url=credentials.get("api_base_url"),
    )


def _status_id(raw: str) -> str:
    """Extract a numeric status id from a Mastodon status URL or a bare id."""
    m = re.search(r"(\d+)/?$", raw.strip())
    return m.group(1) if m else raw.strip()


def _account_handle(status: dict[str, Any]) -> str | None:
    account = status.get("account") or {}
    return account.get("acct") or account.get("username")


class MastodonAdapter(PlatformAdapter):
    platform = Platform.MASTODON

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client_factory

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.MASTODON,
            publish_mode=PublishMode.API,
            can_publish=True,
            can_comment=True,
            can_read=True,
            can_search=True,
            can_react=True,
            can_vote=False,
            supports_media=False,
            requires_bot_flag=True,
            self_label_supported=False,
            max_text_len=500,
            reaction_kinds=("favourite", "boost"),
        )

    def _client(self, session: AdapterSession) -> Any:
        return self._client_factory(session.credentials)

    @staticmethod
    async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await to_thread.run_sync(partial(fn, *args, **kwargs))

    async def authenticate(self, session: AdapterSession) -> AuthState:
        m = self._client(session)
        acct = await self._call(m.account_verify_credentials)
        return AuthState(
            ok=True,
            platform_user_id=str(acct.get("id")),
            display_name=acct.get("display_name") or acct.get("username"),
            scopes=["read", "write"],
            detail={"acct": acct.get("acct")},
        )

    async def refresh_credentials(self, session: AdapterSession) -> RefreshResult:
        return RefreshResult(auth=await self.authenticate(session), new_credentials=None)

    async def health_check(self, session: AdapterSession) -> HealthReport:
        m = self._client(session)
        try:
            acct = await self._call(m.account_verify_credentials)
            return HealthReport(status=HealthStatus.OK, detail={"username": acct.get("username")})
        except Exception as exc:
            return HealthReport(status=HealthStatus.DEGRADED, error=str(exc))

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        m = self._client(session)
        acct = await self._call(partial(m.account_update_credentials, bot=True))
        return ComplianceState(
            ok=True,
            bot_flag_set=bool(acct.get("bot", True)),
            detail={"mechanism": "account bot flag"},
        )

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        m = self._client(session)
        status = await self._call(partial(m.status_post, draft.body, visibility="public"))
        return ActionResult(ok=True, external_id=str(status.get("id")), url=status.get("url"))

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"target": target.raw, "simulated": True})
        m = self._client(session)
        parent_id = target.parent_id or _status_id(target.raw)
        status = await self._call(partial(m.status_post, draft.body, in_reply_to_id=parent_id))
        return ActionResult(ok=True, external_id=str(status.get("id")), url=status.get("url"))

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        m = self._client(session)
        status = await self._call(m.status, _status_id(target.raw))
        return ReadResult(
            items=[
                {
                    "id": str(status.get("id")),
                    "content": status.get("content"),
                    "author": _account_handle(status),
                }
            ]
        )

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        m = self._client(session)
        res = await self._call(m.search_v2, query)
        statuses = (res.get("statuses") or [])[:limit]
        return SearchResult(
            items=[
                {"id": str(s.get("id")), "content": s.get("content"), "author": _account_handle(s)}
                for s in statuses
            ],
            detail={"query": query},
        )

    async def react(
        self, session: AdapterSession, target: TargetRef, kind: str, *, dry_run: bool
    ) -> ActionResult:
        k = kind.lower()
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"kind": k, "simulated": True})
        m = self._client(session)
        sid = target.parent_id or _status_id(target.raw)
        if k in _BOOST_KINDS:
            await self._call(m.status_reblog, sid)
        else:
            await self._call(m.status_favourite, sid)
        return ActionResult(ok=True, external_id=str(sid), detail={"kind": k})

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        return TargetRef(
            raw=raw,
            platform=Platform.MASTODON,
            kind="status",
            parent_id=_status_id(raw),
            is_owned=False,
            resolved=True,
        )
