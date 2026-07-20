"""The platform adapter contract.

Every platform implements the same async interface; *capabilities are data* so the policy engine
reasons about all platforms uniformly. Adapters receive an :class:`AdapterSession` (the account plus
its decrypted credentials) — they never touch the vault directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..domain.enums import HealthStatus, Platform
from ..domain.models import Account, Capabilities, ContentDraft, TargetRef


class UnsupportedCapability(RuntimeError):
    """Raised if a verb reaches an adapter that does not implement it (defense in depth — the guard
    should already have blocked it via capability checks)."""


@dataclass
class AdapterSession:
    """What an adapter needs to act: the account object and its decrypted credentials."""

    account: Account
    credentials: dict[str, Any] = field(default_factory=dict)


# ---- Result types (serialize into audit `platform_result`) ----
class AuthState(BaseModel):
    ok: bool
    platform_user_id: str | None = None
    display_name: str | None = None
    scopes: list[str] = []
    detail: dict[str, Any] = {}


class RefreshResult(BaseModel):
    auth: AuthState
    # New credential material to persist back into the vault, if the refresh rotated tokens.
    new_credentials: dict[str, Any] | None = None


class HealthReport(BaseModel):
    status: HealthStatus
    error: str | None = None
    detail: dict[str, Any] = {}


class ComplianceState(BaseModel):
    """Self-identification state on the platform (bot flag / self-label)."""

    ok: bool
    bot_flag_set: bool = False
    self_label: str | None = None
    detail: dict[str, Any] = {}


class ActionResult(BaseModel):
    ok: bool
    external_id: str | None = None
    url: str | None = None
    dry_run: bool = False
    detail: dict[str, Any] = {}


class ReadResult(BaseModel):
    items: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}


class SearchResult(BaseModel):
    items: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}


class PlatformAdapter(ABC):
    """Base adapter. Unsupported verbs raise :class:`UnsupportedCapability` by default; a real
    adapter overrides only what its platform supports."""

    platform: Platform

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Static description of what this adapter can do."""

    async def authenticate(self, session: AdapterSession) -> AuthState:
        raise UnsupportedCapability(f"{self.platform}: authenticate")

    async def refresh_credentials(self, session: AdapterSession) -> RefreshResult:
        # Default: nothing to refresh.
        return RefreshResult(auth=AuthState(ok=True), new_credentials=None)

    async def health_check(self, session: AdapterSession) -> HealthReport:
        raise UnsupportedCapability(f"{self.platform}: health_check")

    async def ensure_self_identification(self, session: AdapterSession) -> ComplianceState:
        # Platforms without a bot flag/self-label requirement are compliant by default.
        return ComplianceState(ok=True)

    async def publish(self, session: AdapterSession, draft: ContentDraft, *, dry_run: bool) -> ActionResult:
        raise UnsupportedCapability(f"{self.platform}: publish")

    async def comment(
        self, session: AdapterSession, target: TargetRef, draft: ContentDraft, *, dry_run: bool
    ) -> ActionResult:
        raise UnsupportedCapability(f"{self.platform}: comment")

    async def read(self, session: AdapterSession, target: TargetRef) -> ReadResult:
        raise UnsupportedCapability(f"{self.platform}: read")

    async def search(self, session: AdapterSession, query: str, *, limit: int = 25) -> SearchResult:
        raise UnsupportedCapability(f"{self.platform}: search")

    async def react(
        self, session: AdapterSession, target: TargetRef, kind: str, *, dry_run: bool
    ) -> ActionResult:
        raise UnsupportedCapability(f"{self.platform}: react")

    async def resolve_target(self, session: AdapterSession, raw: str) -> TargetRef:
        # Default: pass the raw reference through unresolved.
        return TargetRef(raw=raw, platform=self.platform, resolved=False)
