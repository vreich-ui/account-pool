"""In-memory stand-in for a synchronous ``Mastodon`` client (methods are sync; the adapter calls
them through ``anyio.to_thread``)."""

from __future__ import annotations

from typing import Any


class FakeMastodonClient:
    def __init__(self, username: str = "brandmasto") -> None:
        self.username = username
        self.bot = False
        self.posted: list[dict[str, Any]] = []
        self.favourited: list[str] = []
        self.reblogged: list[str] = []

    def account_verify_credentials(self) -> dict[str, Any]:
        return {
            "id": 1,
            "username": self.username,
            "acct": self.username,
            "display_name": "Brand Voice",
            "bot": self.bot,
        }

    def account_update_credentials(self, bot: bool = False) -> dict[str, Any]:
        self.bot = bot
        return {"id": 1, "username": self.username, "bot": bot}

    def status_post(
        self, body: str, visibility: str | None = None, in_reply_to_id: str | None = None
    ) -> dict[str, Any]:
        sid = 100 + len(self.posted)
        self.posted.append({"body": body, "reply_to": in_reply_to_id})
        return {
            "id": sid,
            "url": f"https://masto.example/{sid}",
            "content": body,
            "account": {"acct": self.username},
        }

    def status(self, sid: Any) -> dict[str, Any]:
        return {"id": sid, "content": "a toot", "account": {"acct": "someone"}}

    def status_favourite(self, sid: Any) -> dict[str, Any]:
        self.favourited.append(str(sid))
        return {"id": sid}

    def status_reblog(self, sid: Any) -> dict[str, Any]:
        self.reblogged.append(str(sid))
        return {"id": sid}

    def search_v2(self, query: str) -> dict[str, Any]:
        return {
            "statuses": [{"id": 7, "content": f"{query} result", "account": {"acct": "poster"}}],
            "accounts": [],
            "hashtags": [],
        }


def mastodon_registry(client: FakeMastodonClient):
    from account_pool.adapters.mastodon import MastodonAdapter
    from account_pool.adapters.registry import default_registry
    from account_pool.domain.enums import Platform

    reg = default_registry()
    reg.register(Platform.MASTODON, lambda: MastodonAdapter(client_factory=lambda creds: client))
    return reg
