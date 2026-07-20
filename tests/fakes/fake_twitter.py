"""In-memory stand-in for a synchronous ``tweepy.Client`` (the adapter calls it via to_thread).

``create_tweet`` returns a Response whose ``.data`` is a dict (as tweepy does); the user/tweet
lookups return objects with attributes."""

from __future__ import annotations

from typing import Any


class _Resp:
    def __init__(self, data: Any) -> None:
        self.data = data


class _User:
    def __init__(self, id_: str, username: str, name: str) -> None:
        self.id = id_
        self.username = username
        self.name = name


class _Tweet:
    def __init__(self, id_: str, text: str = "a tweet", author_id: str = "999") -> None:
        self.id = id_
        self.text = text
        self.author_id = author_id


class FakeTweepyClient:
    def __init__(self, user_id: str = "42", username: str = "brandx") -> None:
        self._user = _User(user_id, username, "Brand X")
        self.tweets: list[dict[str, Any]] = []
        self.likes: list[str] = []
        self.retweets: list[str] = []

    def get_me(self) -> _Resp:
        return _Resp(self._user)

    def create_tweet(self, text: str | None = None, in_reply_to_tweet_id: str | None = None) -> _Resp:
        tid = str(1000 + len(self.tweets))
        self.tweets.append({"text": text, "reply_to": in_reply_to_tweet_id})
        return _Resp({"id": tid, "text": text})

    def get_tweet(self, tid: Any) -> _Resp:
        return _Resp(_Tweet(str(tid)))

    def search_recent_tweets(self, query: str, max_results: int = 10) -> _Resp:
        return _Resp([_Tweet("1", f"{query} a"), _Tweet("2", f"{query} b")])

    def like(self, tid: Any) -> _Resp:
        self.likes.append(str(tid))
        return _Resp({"liked": True})

    def retweet(self, tid: Any) -> _Resp:
        self.retweets.append(str(tid))
        return _Resp({"retweeted": True})


def twitter_registry(client: FakeTweepyClient):
    from account_pool.adapters.registry import default_registry
    from account_pool.adapters.twitter import TwitterAdapter
    from account_pool.domain.enums import Platform

    reg = default_registry()
    reg.register(Platform.TWITTER, lambda: TwitterAdapter(client_factory=lambda creds: client))
    return reg
