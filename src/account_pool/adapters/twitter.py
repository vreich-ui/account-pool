"""X / Twitter adapter (tweepy, v2 API).

tweepy's ``Client`` is synchronous, so calls run in a worker thread via ``anyio.to_thread``.
``publish`` posts a tweet to the account's own timeline; ``comment`` replies; ``react`` likes or
retweets; ``read`` fetches a tweet; ``search`` uses recent search.

Tier caveat: on the free tier, reads (get_tweet / recent search) are heavily limited or unavailable
and will surface as adapter errors. ``reads_enabled=False`` disables the read/search verbs up front
(reported through ``capabilities``) so callers can degrade gracefully instead of hitting 403s.
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
    UnsupportedCapability,
)

ClientFactory = Callable[[dict[str, Any]], Any]

_RETWEET_KINDS = {"retweet", "repost", "boost"}
_CLIENT_KWARGS = {
    "bearer_token",
    "consumer_key",
    "consumer_secret",
    "access_token",
    "access_token_secret",
}


def _default_client_factory(credentials: dict[str, Any]) -> Any:
    import tweepy  # optional dependency

    kwargs = {k: v for k, v in credentials.items() if k in _CLIENT_KWARGS and v is not None}
    return tweepy.Client(**kwargs)


def _tweet_id(raw: str) -> str:
    m = re.search(r"(\d+)/?$", raw.strip())
    return m.group(1) if m else raw.strip()


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


class TwitterAdapter(PlatformAdapter):
    platform = Platform.TWITTER

    def __init__(self, client_factory: ClientFactory | None = None, *, reads_enabled: bool = True) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._reads_enabled = reads_enabled

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.TWITTER,
            publish_mode=PublishMode.API,
            can_publish=True,
            can_comment=True,
            can_read=self._reads_enabled,
            can_search=self._reads_enabled,
            can_react=True,
            can_vote=False,
            supports_media=False,
            requires_bot_flag=False,
            self_label_supported=False,
            max_text_len=280,
            reaction_kinds=("like", "retweet"),
        )

    def _client(self, session: AdapterSession) -> Any:
        return self._client_factory(session.credentials)

    @staticmethod
    async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await to_thread.run_sync(partial(fn, *args, **kwargs))

    async def authenticate(self, session: AdapterSession) -> AuthState:
        client = self._client(session)
        resp = await self._call(client.get_me)
        user = resp.data
        return AuthState(
            ok=user is not None,
            platform_user_id=str(_get(user, "id")) if user else None,
            display_name=_get(user, "username"),
            scopes=["tweet.read", "tweet.write", "users.read"],
        )

    async def refresh_credentials(self, session: AdapterSession) -> RefreshResult:
        return RefreshResult(auth=await self.authenticate(session), new_credentials=None)

    async def health_check(self, session: AdapterSession) -> HealthReport:
        client = self._client(session)
        try:
            resp = await self._call(client.get_me)
            if resp.data is None:
                return HealthReport(status=HealthStatus.REAUTH_NEEDED, error="no authenticated user")
            return HealthReport(status=HealthStatus.OK, detail={"username": _get(resp.data, "username")})
        except Exception as exc:
            return HealthReport(status=HealthStatus.DEGRADED, error=str(exc))

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        # X exposes no API bot flag; automated-account labeling is a manual profile step.
        return ComplianceState(ok=True, detail={"mechanism": "manual automated-account label"})

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        client = self._client(session)
        resp = await self._call(partial(client.create_tweet, text=draft.body))
        return ActionResult(ok=True, external_id=str(_get(resp.data, "id")))

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"target": target.raw, "simulated": True})
        client = self._client(session)
        tid = target.parent_id or _tweet_id(target.raw)
        resp = await self._call(partial(client.create_tweet, text=draft.body, in_reply_to_tweet_id=tid))
        return ActionResult(ok=True, external_id=str(_get(resp.data, "id")))

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        if not self._reads_enabled:
            raise UnsupportedCapability("twitter: reads are disabled (tier)")
        client = self._client(session)
        resp = await self._call(partial(client.get_tweet, _tweet_id(target.raw)))
        tweet = resp.data
        return ReadResult(
            items=[
                {
                    "id": str(_get(tweet, "id")),
                    "text": _get(tweet, "text"),
                    "author_id": str(_get(tweet, "author_id")),
                }
            ]
        )

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        if not self._reads_enabled:
            raise UnsupportedCapability("twitter: search is disabled (tier)")
        client = self._client(session)
        resp = await self._call(
            partial(client.search_recent_tweets, query, max_results=min(max(limit, 10), 100))
        )
        tweets = resp.data or []
        return SearchResult(
            items=[{"id": str(_get(t, "id")), "text": _get(t, "text")} for t in tweets],
            detail={"query": query},
        )

    async def react(
        self, session: AdapterSession, target: TargetRef, kind: str, *, dry_run: bool
    ) -> ActionResult:
        k = kind.lower()
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"kind": k, "simulated": True})
        client = self._client(session)
        tid = target.parent_id or _tweet_id(target.raw)
        if k in _RETWEET_KINDS:
            await self._call(client.retweet, tid)
        else:
            await self._call(client.like, tid)
        return ActionResult(ok=True, external_id=str(tid), detail={"kind": k})

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        return TargetRef(
            raw=raw,
            platform=Platform.TWITTER,
            kind="tweet",
            parent_id=_tweet_id(raw),
            is_owned=False,
            resolved=True,
        )
