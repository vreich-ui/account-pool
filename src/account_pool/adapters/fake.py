"""In-memory adapter used for tests and global dry-run.

It records every call and, on a real (non-dry-run) write, stores the content so tests can assert on
it. It performs no network I/O. ``resolve_target`` treats a ``owned:`` prefix as an owned channel so
tests can exercise both autonomy paths.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import HealthStatus, Platform
from ..domain.models import Capabilities, ContentDraft, TargetRef
from .base import (
    ActionResult,
    AdapterSession,
    AuthState,
    ComplianceState,
    HealthReport,
    PlatformAdapter,
    ReadResult,
    SearchResult,
)


class FakeAdapter(PlatformAdapter):
    def __init__(
        self,
        platform: Platform = Platform.MASTODON,
        capabilities: Capabilities | None = None,
    ) -> None:
        self.platform = platform
        self._caps = capabilities or Capabilities(
            platform=platform,
            can_publish=True,
            can_comment=True,
            can_read=True,
            can_search=True,
            can_react=True,
            can_vote=(platform == Platform.REDDIT),
            supports_media=True,
            requires_bot_flag=(platform == Platform.MASTODON),
            self_label_supported=(platform == Platform.BLUESKY),
            max_text_len=5000,
            reaction_kinds=("like", "boost"),
        )
        # Observability for assertions:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.published: list[dict[str, Any]] = []
        self.comments: list[dict[str, Any]] = []
        self.reactions: list[dict[str, Any]] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"{self.platform.value}_ext_{self._seq}"

    def capabilities(self) -> Capabilities:
        return self._caps

    async def authenticate(self, session: AdapterSession) -> AuthState:
        self.calls.append(("authenticate", {"account": session.account.account_id}))
        return AuthState(
            ok=True,
            platform_user_id=f"{self.platform.value}:{session.account.handle}",
            display_name=session.account.display_name or session.account.handle,
            scopes=["identity", "submit", "read"],
        )

    async def health_check(self, session: AdapterSession) -> HealthReport:
        self.calls.append(("health_check", {"account": session.account.account_id}))
        return HealthReport(status=HealthStatus.OK, detail={"simulated": True})

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        self.calls.append(("ensure_self_identification", {"account": session.account.account_id}))
        needs_bot = self._caps.requires_bot_flag
        supports_label = self._caps.self_label_supported
        return ComplianceState(
            ok=True,
            bot_flag_set=needs_bot,
            self_label="automated" if supports_label else None,
        )

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        self.calls.append(("publish", {"draft": draft.draft_id, "dry_run": dry_run}))
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        ext = self._next_id()
        self.published.append({"account": session.account.account_id, "body": draft.body, "id": ext})
        return ActionResult(ok=True, external_id=ext, url=f"https://fake/{ext}")

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        self.calls.append(("comment", {"target": target.raw, "dry_run": dry_run}))
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        ext = self._next_id()
        self.comments.append({"target": target.raw, "body": draft.body, "id": ext})
        return ActionResult(ok=True, external_id=ext, url=f"https://fake/{ext}")

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        self.calls.append(("read", {"target": target.raw}))
        return ReadResult(items=[{"id": target.raw, "text": "simulated item", "author": "someone"}])

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        self.calls.append(("search", {"query": query, "limit": limit}))
        return SearchResult(
            items=[{"id": f"result-{i}", "text": f"{query} #{i}"} for i in range(min(limit, 3))]
        )

    async def react(
        self, session: AdapterSession, target: TargetRef, kind: str, *, dry_run: bool
    ) -> ActionResult:
        self.calls.append(("react", {"target": target.raw, "kind": kind, "dry_run": dry_run}))
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        ext = self._next_id()
        self.reactions.append({"target": target.raw, "kind": kind, "id": ext})
        return ActionResult(ok=True, external_id=ext)

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        # Convention for tests: an "owned:" prefix marks the pool's own channel.
        is_owned = raw.startswith("owned:")
        return TargetRef(
            raw=raw,
            platform=self.platform,
            is_owned=is_owned,
            container=raw.split("/")[0] if "/" in raw else None,
            resolved=True,
        )
