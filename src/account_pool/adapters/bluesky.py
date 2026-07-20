"""Bluesky adapter (atproto AT Protocol SDK, async).

``publish`` sends a post to the account's own feed (own channel); ``comment`` replies to a post
(building an AT-Protocol reply ref from the parent's strong ref); ``react`` likes or reposts; ``read``
and ``search`` fetch posts. Credentials must use an **app password**, never the main password.

Bluesky has no first-class account "bot flag"; self-identification is via a self-label/profile
disclosure. ``ensure_self_identification`` records the automated self-label the policy pipeline
requires — applying a durable profile label is a follow-up (flagged in the design).

A fresh client is created and logged in per call for simplicity; a session cache is a later
optimization.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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

_REPOST_KINDS = {"repost", "boost"}


def _default_client_factory(credentials: dict[str, Any]) -> Any:
    from atproto import AsyncClient  # optional dependency

    return AsyncClient()


def _post_text(post: Any) -> str | None:
    record = getattr(post, "record", None)
    return getattr(record, "text", None) if record is not None else None


def _post_author(post: Any) -> str | None:
    author = getattr(post, "author", None)
    return getattr(author, "handle", None) if author is not None else None


class BlueskyAdapter(PlatformAdapter):
    platform = Platform.BLUESKY

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client_factory

    def capabilities(self) -> Capabilities:
        return Capabilities(
            platform=Platform.BLUESKY,
            publish_mode=PublishMode.API,
            can_publish=True,
            can_comment=True,
            can_read=True,
            can_search=True,
            can_react=True,
            can_vote=False,
            supports_media=False,
            requires_bot_flag=False,
            self_label_supported=True,
            max_text_len=300,
            reaction_kinds=("like", "repost"),
        )

    async def _client(self, session: AdapterSession) -> Any:
        client = self._client_factory(session.credentials)
        creds = session.credentials
        identifier = creds.get("identifier") or creds.get("handle") or session.account.handle
        password = creds.get("app_password") or creds.get("password")
        await client.login(identifier, password)
        return client

    async def _strong_ref(self, client: Any, uri: str) -> Any:
        from atproto import models

        posts = await client.get_posts([uri])
        post = posts.posts[0]
        return models.ComAtprotoRepoStrongRef.Main(uri=post.uri, cid=post.cid)

    async def authenticate(self, session: AdapterSession) -> AuthState:
        client = await self._client(session)
        me = client.me
        return AuthState(
            ok=True,
            platform_user_id=getattr(me, "did", None),
            display_name=getattr(me, "handle", None),
            scopes=["atproto"],
        )

    async def refresh_credentials(self, session: AdapterSession) -> RefreshResult:
        return RefreshResult(auth=await self.authenticate(session), new_credentials=None)

    async def health_check(self, session: AdapterSession) -> HealthReport:
        try:
            client = await self._client(session)
            return HealthReport(status=HealthStatus.OK, detail={"handle": getattr(client.me, "handle", None)})
        except Exception as exc:
            return HealthReport(status=HealthStatus.REAUTH_NEEDED, error=str(exc))

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        # No first-class bot flag on Bluesky; disclosure is via a self-label / profile note.
        return ComplianceState(
            ok=True,
            self_label="automated",
            detail={"mechanism": "self-label/profile disclosure"},
        )

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"simulated": True})
        client = await self._client(session)
        resp = await client.send_post(text=draft.body)
        return ActionResult(
            ok=True, external_id=getattr(resp, "uri", None), detail={"cid": getattr(resp, "cid", None)}
        )

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"target": target.raw, "simulated": True})
        from atproto import models

        client = await self._client(session)
        parent = await self._strong_ref(client, target.raw)
        reply_ref = models.AppBskyFeedPost.ReplyRef(parent=parent, root=parent)
        resp = await client.send_post(text=draft.body, reply_to=reply_ref)
        return ActionResult(
            ok=True, external_id=getattr(resp, "uri", None), detail={"cid": getattr(resp, "cid", None)}
        )

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        client = await self._client(session)
        posts = await client.get_posts([target.raw])
        return ReadResult(
            items=[
                {"uri": getattr(p, "uri", None), "text": _post_text(p), "author": _post_author(p)}
                for p in posts.posts
            ]
        )

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        from atproto import models

        client = await self._client(session)
        params = models.AppBskyFeedSearchPosts.Params(q=query, limit=min(limit, 25))
        res = await client.app.bsky.feed.search_posts(params)
        return SearchResult(
            items=[
                {"uri": getattr(p, "uri", None), "text": _post_text(p), "author": _post_author(p)}
                for p in res.posts
            ],
            detail={"query": query},
        )

    async def react(
        self, session: AdapterSession, target: TargetRef, kind: str, *, dry_run: bool
    ) -> ActionResult:
        k = kind.lower()
        if dry_run:
            return ActionResult(ok=True, dry_run=True, detail={"kind": k, "simulated": True})
        client = await self._client(session)
        ref = await self._strong_ref(client, target.raw)
        if k in _REPOST_KINDS:
            resp = await client.repost(ref.uri, ref.cid)
        else:
            resp = await client.like(ref.uri, ref.cid)
        return ActionResult(ok=True, external_id=getattr(resp, "uri", None), detail={"kind": k})

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        return TargetRef(raw=raw, platform=Platform.BLUESKY, kind="post", is_owned=False, resolved=True)
