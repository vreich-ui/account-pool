"""Reddit adapter (asyncpraw).

Reads and authentication hit the real API; writes honor ``dry_run`` (no submission is created when
dry-run is on). ``publish`` targets the account's **own profile** (``u_<username>``) — the account's
own space — so it maps onto the M0 "publish to own channel" autonomy path. ``comment`` replies to a
submission or comment resolved from a URL/id; third-party targets route to approval via the guard.

There is deliberately **no voting method**: Reddit reacting *is* voting, which the manipulation guard
hard-blocks and which is absent from Reddit's allowed verbs, so the guard never reaches a vote path.
Reddit has no per-account "bot flag"; compliance rests on a descriptive User-Agent, honoring
subreddit rules, the self-promo ratio, and rate limits — all enforced by the policy pipeline.

The asyncpraw client is created through an injectable factory so tests can drive the adapter with a
fake client and never touch the network.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

from ..domain.enums import HealthStatus, Platform, PublishMode
from ..domain.models import Capabilities, ContentDraft, TargetRef
from .base import (
    ActionResult,
    AdapterSession,
    AuthState,
    ComplianceState,
    ContentInvalid,
    HealthReport,
    PlatformAdapter,
    ReadResult,
    RefreshResult,
    SearchResult,
)

ClientFactory = Callable[[dict[str, Any]], Any]

_DEFAULT_USER_AGENT = "account-pool/0.1 (compliance-first social account pool)"
_CLIENT_KWARGS = {
    "client_id",
    "client_secret",
    "user_agent",
    "refresh_token",
    "username",
    "password",
    "redirect_uri",
}


def _default_client_factory(credentials: dict[str, Any]) -> Any:
    """Build a real ``asyncpraw.Reddit`` from stored credentials (imported lazily)."""
    import asyncpraw  # optional dependency; only needed for real Reddit use

    kwargs = {k: v for k, v in credentials.items() if k in _CLIENT_KWARGS and v is not None}
    kwargs.setdefault("user_agent", _DEFAULT_USER_AGENT)
    return asyncpraw.Reddit(**kwargs)


# ---- reference parsing ---------------------------------------------------------------
_FULLNAME_RE = re.compile(r"^(t[1235])_([a-z0-9]+)$", re.IGNORECASE)
_URL_RE = re.compile(
    r"reddit\.com/r/(?P<sub>[A-Za-z0-9_]+)/comments/(?P<subid>[a-z0-9]+)"
    r"(?:/[^/\s]*(?:/(?P<cid>[a-z0-9]+))?)?",
    re.IGNORECASE,
)
_SUBREDDIT_RE = re.compile(r"^/?r/(?P<sub>[A-Za-z0-9_]+)/?$", re.IGNORECASE)
_USER_RE = re.compile(r"^/?u(?:ser)?/(?P<user>[A-Za-z0-9_-]+)/?$", re.IGNORECASE)
_FULLNAME_KIND = {"t1": "comment", "t3": "submission", "t5": "subreddit", "t2": "user"}


def parse_ref(raw: str) -> dict[str, Any]:
    """Parse a Reddit URL, fullname (t3_/t1_), r/sub, u/user, or bare id into a structured ref."""
    raw = raw.strip()
    m = _FULLNAME_RE.match(raw)
    if m:
        return {
            "kind": _FULLNAME_KIND[m.group(1).lower()],
            "id": m.group(2),
            "subreddit": None,
            "parent_id": None,
        }
    m = _URL_RE.search(raw)
    if m:
        if m.group("cid"):
            return {
                "kind": "comment",
                "id": m.group("cid"),
                "subreddit": m.group("sub"),
                "parent_id": m.group("subid"),
            }
        return {
            "kind": "submission",
            "id": m.group("subid"),
            "subreddit": m.group("sub"),
            "parent_id": None,
        }
    m = _SUBREDDIT_RE.match(raw)
    if m:
        return {"kind": "subreddit", "id": m.group("sub"), "subreddit": m.group("sub"), "parent_id": None}
    m = _USER_RE.match(raw)
    if m:
        user = m.group("user")
        return {"kind": "user", "id": user, "subreddit": f"u_{user}", "parent_id": None}
    return {"kind": "submission", "id": raw, "subreddit": None, "parent_id": None}


async def _aclose(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _permalink(obj: Any) -> str | None:
    p = getattr(obj, "permalink", None)
    return f"https://www.reddit.com{p}" if p else None


def _ext_id(obj: Any) -> str | None:
    return getattr(obj, "fullname", None) or getattr(obj, "id", None)


def _author(obj: Any) -> str | None:
    author = getattr(obj, "author", None)
    return getattr(author, "name", None) if author is not None else None


def _post_summary(post: Any, *, include_body: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": getattr(post, "id", None),
        "fullname": getattr(post, "fullname", None),
        "title": getattr(post, "title", None),
        "subreddit": str(getattr(post, "subreddit", "") or "") or None,
        "author": _author(post),
        "score": getattr(post, "score", None),
        "num_comments": getattr(post, "num_comments", None),
        "permalink": _permalink(post),
    }
    if include_body:
        summary["selftext"] = getattr(post, "selftext", None)
    return summary


class RedditAdapter(PlatformAdapter):
    platform = Platform.REDDIT

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client_factory

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.REDDIT,
            publish_mode=PublishMode.API,
            can_publish=True,
            can_comment=True,
            can_read=True,
            can_search=True,
            can_react=False,  # reacting on Reddit == voting; not offered as an automated action
            can_vote=True,  # capability exists but is hard-blocked by the manipulation guard
            supports_media=False,
            requires_bot_flag=False,  # Reddit has no account bot flag
            self_label_supported=False,
            max_text_len=40000,
            reaction_kinds=(),
        )

    def _client(self, session: AdapterSession) -> Any:
        return self._client_factory(session.credentials)

    async def authenticate(self, session: AdapterSession) -> AuthState:
        client = self._client(session)
        try:
            me = await client.user.me()
            if me is None:
                return AuthState(ok=False, detail={"error": "no authenticated user"})
            return AuthState(
                ok=True,
                platform_user_id=getattr(me, "fullname", None) or f"t2_{me.name}",
                display_name=me.name,
                scopes=["identity", "submit", "read", "history"],
            )
        finally:
            await _aclose(client)

    async def refresh_credentials(self, session: AdapterSession) -> RefreshResult:
        # asyncpraw refreshes access tokens internally from the stored refresh_token; nothing to
        # persist here. Confirm the session still authenticates.
        auth = await self.authenticate(session)
        return RefreshResult(auth=auth, new_credentials=None)

    async def health_check(self, session: AdapterSession) -> HealthReport:
        client = self._client(session)
        try:
            me = await client.user.me()
            if me is None:
                return HealthReport(status=HealthStatus.REAUTH_NEEDED, error="no authenticated user")
            return HealthReport(status=HealthStatus.OK, detail={"username": me.name})
        except Exception as exc:  # network/auth failure — report, don't crash the pipeline
            return HealthReport(status=HealthStatus.DEGRADED, error=str(exc))
        finally:
            await _aclose(client)

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        # No account-level bot flag on Reddit; compliance is via User-Agent + rules + rate limits.
        return ComplianceState(
            ok=True,
            detail={"mechanism": "user_agent+subreddit_rules+ratelimit", "bot_flag": "n/a"},
        )

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        title = (draft.title or "").strip()
        if not title:
            raise ContentInvalid("Reddit submissions require a title")
        profile_sub = f"u_{session.account.handle}"
        if dry_run:
            return ActionResult(
                ok=True,
                dry_run=True,
                detail={"subreddit": profile_sub, "title": title, "simulated": True},
            )
        client = self._client(session)
        try:
            subreddit = await client.subreddit(profile_sub)
            submission = await subreddit.submit(title, selftext=draft.body)
            return ActionResult(
                ok=True,
                external_id=_ext_id(submission),
                url=_permalink(submission),
                detail={"subreddit": profile_sub},
            )
        finally:
            await _aclose(client)

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"target": target.raw, "simulated": True})
        client = self._client(session)
        try:
            parent = await self._fetch_parent(client, target)
            reply = await parent.reply(draft.body)
            return ActionResult(
                ok=True,
                external_id=_ext_id(reply),
                url=_permalink(reply),
                detail={"target": target.raw},
            )
        finally:
            await _aclose(client)

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        client = self._client(session)
        try:
            ref = parse_ref(target.raw)
            if ref["kind"] == "comment":
                comment = await client.comment(id=ref["id"])
                return ReadResult(
                    items=[
                        {
                            "id": ref["id"],
                            "kind": "comment",
                            "body": getattr(comment, "body", None),
                            "author": _author(comment),
                        }
                    ]
                )
            submission = await client.submission(id=ref["id"])
            return ReadResult(items=[_post_summary(submission, include_body=True)])
        finally:
            await _aclose(client)

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        subname, terms = _split_query(query)
        client = self._client(session)
        try:
            subreddit = await client.subreddit(subname or "all")
            items: list[dict[str, Any]] = []
            async for post in subreddit.search(terms, limit=limit):
                items.append(_post_summary(post))
            return SearchResult(items=items, detail={"subreddit": subname or "all", "query": terms})
        finally:
            await _aclose(client)

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        ref = parse_ref(raw)
        own_profile = f"u_{session.account.handle}".lower()
        is_owned = (ref["subreddit"] or "").lower() == own_profile
        return TargetRef(
            raw=raw,
            platform=Platform.REDDIT,
            kind=ref["kind"],
            container=ref["subreddit"],
            parent_id=ref["parent_id"],
            is_owned=is_owned,
            resolved=True,
        )

    async def _fetch_parent(self, client: Any, target: TargetRef) -> Any:
        ref = parse_ref(target.raw)
        kind = target.kind or ref["kind"]
        if kind == "comment":
            return await client.comment(id=ref["id"])
        return await client.submission(id=ref["id"])


def _split_query(query: str) -> tuple[str | None, str]:
    """Split a query like 'r/python async praw' into ('python', 'async praw')."""
    m = re.match(r"^/?r/(?P<sub>[A-Za-z0-9_]+)\s+(?P<terms>.+)$", query.strip(), re.IGNORECASE)
    if m:
        return m.group("sub"), m.group("terms").strip()
    return None, query.strip()
