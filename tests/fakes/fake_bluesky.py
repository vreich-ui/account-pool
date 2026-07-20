"""In-memory stand-in for an async ``atproto`` client. Only the surface the adapter uses is
implemented; the adapter still builds the real atproto model objects, so those paths are exercised."""

from __future__ import annotations

from typing import Any


class _Me:
    def __init__(self, did: str, handle: str) -> None:
        self.did = did
        self.handle = handle


class _Record:
    def __init__(self, text: str) -> None:
        self.text = text


class _Author:
    def __init__(self, handle: str) -> None:
        self.handle = handle


class _Post:
    def __init__(self, uri: str, cid: str = "bafycid", text: str = "a post", author: str = "someone") -> None:
        self.uri = uri
        self.cid = cid
        self.record = _Record(text)
        self.author = _Author(author)


class _Resp:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FeedNS:
    async def search_posts(self, params: Any) -> Any:
        q = getattr(params, "q", "")
        return _Resp(
            posts=[_Post(f"at://did:plc:x/app.bsky.feed.post/{i}", text=f"{q} #{i}") for i in range(2)]
        )


class _BskyNS:
    def __init__(self) -> None:
        self.feed = _FeedNS()


class _AppNS:
    def __init__(self) -> None:
        self.bsky = _BskyNS()


class FakeBlueskyClient:
    def __init__(self, handle: str = "brand.bsky.social", did: str = "did:plc:abc123") -> None:
        self._handle = handle
        self._did = did
        self.me: _Me | None = None
        self.posts: list[dict[str, Any]] = []
        self.likes: list[tuple[str, str]] = []
        self.reposts: list[tuple[str, str]] = []
        self.app = _AppNS()

    async def login(self, identifier: str, password: str | None) -> _Me:
        self.me = _Me(self._did, self._handle)
        return self.me

    async def send_post(self, text: str, reply_to: Any = None) -> Any:
        uri = f"at://{self._did}/app.bsky.feed.post/{len(self.posts)}"
        self.posts.append({"text": text, "reply_to": reply_to})
        return _Resp(uri=uri, cid="bafycid")

    async def get_posts(self, uris: list[str]) -> Any:
        return _Resp(posts=[_Post(u) for u in uris])

    async def like(self, uri: str, cid: str) -> Any:
        self.likes.append((uri, cid))
        return _Resp(uri=f"{uri}/like", cid="c")

    async def repost(self, uri: str, cid: str) -> Any:
        self.reposts.append((uri, cid))
        return _Resp(uri=f"{uri}/repost", cid="c")


def bluesky_registry(client: FakeBlueskyClient):
    from account_pool.adapters.bluesky import BlueskyAdapter
    from account_pool.adapters.registry import default_registry
    from account_pool.domain.enums import Platform

    reg = default_registry()
    reg.register(Platform.BLUESKY, lambda: BlueskyAdapter(client_factory=lambda creds: client))
    return reg
