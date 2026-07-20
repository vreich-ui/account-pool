"""A minimal in-memory stand-in for an ``asyncpraw.Reddit`` client.

It implements just the async surface the RedditAdapter touches (``user.me``, ``subreddit``,
``submission``, ``comment``, ``close``), records writes for assertions, and performs no I/O.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class _Author:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSubmission:
    def __init__(
        self,
        id_: str,
        title: str = "a title",
        subreddit: str = "python",
        author: str = "someone",
        selftext: str = "post body",
    ) -> None:
        self.id = id_
        self.fullname = f"t3_{id_}"
        self.title = title
        self.subreddit = subreddit
        self.author = _Author(author)
        self.selftext = selftext
        self.score = 12
        self.num_comments = 3
        self.permalink = f"/r/{subreddit}/comments/{id_}/slug/"
        self.replies: list[FakeComment] = []

    async def reply(self, body: str) -> FakeComment:
        c = FakeComment("reply1", body=body, subreddit=str(self.subreddit))
        self.replies.append(c)
        return c


class FakeComment:
    def __init__(
        self, id_: str, body: str = "a comment", subreddit: str = "python", author: str = "someone"
    ) -> None:
        self.id = id_
        self.fullname = f"t1_{id_}"
        self.body = body
        self.author = _Author(author)
        self.permalink = f"/r/{subreddit}/comments/xyz/slug/{id_}/"
        self.replies: list[FakeComment] = []

    async def reply(self, body: str) -> FakeComment:
        c = FakeComment("reply2", body=body)
        self.replies.append(c)
        return c


class _FakeUserNS:
    def __init__(self, name: str | None) -> None:
        self._name = name

    async def me(self) -> Any:
        if not self._name:
            return None
        return _Author(self._name)


class FakeSubreddit:
    def __init__(self, name: str, client: FakeRedditClient) -> None:
        self.display_name = name
        self._client = client

    async def submit(self, title: str, selftext: str | None = None) -> FakeSubmission:
        s = FakeSubmission(
            "newpost",
            title=title,
            subreddit=self.display_name,
            author=self._client.username or "someone",
            selftext=selftext or "",
        )
        self._client.submitted.append(s)
        return s

    async def search(self, query: str, limit: int = 25) -> AsyncIterator[FakeSubmission]:
        for i in range(min(limit, 2)):
            yield FakeSubmission(f"res{i}", title=f"{query} #{i}", subreddit=self.display_name)


class FakeRedditClient:
    def __init__(self, username: str = "brand_reddit", authed: bool = True) -> None:
        self.username = username if authed else None
        self.user = _FakeUserNS(self.username)
        self.submitted: list[FakeSubmission] = []
        self.closed = False

    async def subreddit(self, name: str) -> FakeSubreddit:
        return FakeSubreddit(name, self)

    async def submission(self, id: str | None = None) -> FakeSubmission:  # noqa: A002
        return FakeSubmission(id or "abc123", subreddit="python")

    async def comment(self, id: str | None = None) -> FakeComment:  # noqa: A002
        return FakeComment(id or "def456", subreddit="python")

    async def close(self) -> None:
        self.closed = True


def reddit_registry(client: FakeRedditClient):
    """A registry with Reddit backed by a RedditAdapter driving ``client``; fake everywhere else."""
    from account_pool.adapters.reddit import RedditAdapter
    from account_pool.adapters.registry import default_registry
    from account_pool.domain.enums import Platform

    reg = default_registry()
    reg.register(Platform.REDDIT, lambda: RedditAdapter(client_factory=lambda creds: client))
    return reg
