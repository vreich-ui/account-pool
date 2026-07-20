"""Medium adapter — **draft-only**.

Medium froze API integration tokens for new apps, so there is no reliable automated publish path.
Publishing is therefore *staged* by the actions service (no live post is made), and this adapter's
``publish`` raises as defense-in-depth — it never makes a network write. What it does provide is
real **review**: reading a Medium user's or publication's recent posts via their public RSS feed.
"""

from __future__ import annotations

from collections.abc import Callable

from anyio import to_thread

from ..domain.enums import HealthStatus, Platform, PublishMode
from ..domain.models import Capabilities, ContentDraft, TargetRef
from ._feeds import default_fetch, parse_feed
from .base import (
    ActionResult,
    AdapterSession,
    AuthState,
    ComplianceState,
    HealthReport,
    PlatformAdapter,
    ReadResult,
    UnsupportedCapability,
)

Fetcher = Callable[[str], str]


def _feed_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("http"):
        return raw
    handle = raw if raw.startswith("@") else f"@{raw}"
    return f"https://medium.com/feed/{handle}"


class MediumAdapter(PlatformAdapter):
    platform = Platform.MEDIUM

    def __init__(self, feed_fetcher: Fetcher | None = None) -> None:
        self._fetch = feed_fetcher or default_fetch

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.MEDIUM,
            publish_mode=PublishMode.DRAFT_ONLY,
            can_publish=True,  # staged by the service; no live post
            can_comment=False,
            can_read=True,
            can_search=False,
            can_react=False,
            can_vote=False,
            supports_media=False,
            requires_bot_flag=False,
            self_label_supported=False,
            max_text_len=None,
        )

    async def authenticate(self, session: AdapterSession) -> AuthState:
        return AuthState(
            ok=True,
            platform_user_id=session.account.handle,
            display_name=session.account.display_name or session.account.handle,
            detail={"note": "medium api tokens frozen for new apps; draft-only"},
        )

    async def health_check(self, session: AdapterSession) -> HealthReport:
        return HealthReport(status=HealthStatus.OK, detail={"mode": "draft_only"})

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        return ComplianceState(ok=True, detail={"mechanism": "disclosure in post text"})

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        raise UnsupportedCapability(
            "medium is draft-only; content is staged by the service and never live-posted"
        )

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        xml = await to_thread.run_sync(self._fetch, target.raw)
        return ReadResult(items=parse_feed(xml), detail={"feed": target.raw})

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        return TargetRef(raw=_feed_url(raw), platform=Platform.MEDIUM, kind="feed", resolved=True)
