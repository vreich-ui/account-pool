"""Substack adapter — **manual / draft-only**.

Substack has no official public API. Automated posting is therefore out of scope: publishing is
*staged* by the actions service as an export for a human to send, and this adapter's ``publish``
raises as defense-in-depth (no network write). It does provide real **review** — reading a
publication's recent posts via its public RSS feed. Unofficial reverse-engineered write endpoints
are deliberately not used (bot-detection / ToS risk).
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
        return raw if raw.rstrip("/").endswith("feed") else raw.rstrip("/") + "/feed"
    return f"https://{raw}.substack.com/feed"


class SubstackAdapter(PlatformAdapter):
    platform = Platform.SUBSTACK

    def __init__(self, feed_fetcher: Fetcher | None = None) -> None:
        self._fetch = feed_fetcher or default_fetch

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.SUBSTACK,
            publish_mode=PublishMode.MANUAL,
            can_publish=True,  # staged as a manual export by the service; no live post
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
            detail={"note": "no official substack api; read-only + manual export"},
        )

    async def health_check(self, session: AdapterSession) -> HealthReport:
        return HealthReport(status=HealthStatus.OK, detail={"mode": "manual"})

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        return ComplianceState(ok=True, detail={"mechanism": "disclosure in newsletter"})

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        raise UnsupportedCapability(
            "substack has no publish API; content is staged for manual posting, never live-posted"
        )

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        xml = await to_thread.run_sync(self._fetch, target.raw)
        return ReadResult(items=parse_feed(xml), detail={"feed": target.raw})

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        return TargetRef(raw=_feed_url(raw), platform=Platform.SUBSTACK, kind="feed", resolved=True)
