"""Domain objects.

Two governed families:

* **Account** — the *actor* object, "acted upon" by lifecycle verbs (register, authorize, checkout,
  patch, health-check, retire) and which "acts" through :class:`Action`.
* **Action** — the *act* object an external agent submits; it flows
  ``draft -> validate -> (approval) -> execute -> audit``.

Everything is a pydantic v2 model so it serializes cleanly into the JSON payload column used by the
persistence layer. Secrets never appear here — a :class:`Connection` holds only a ``secret_ref``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from .enums import (
    ActionState,
    ActionType,
    AuthType,
    ConnectionProviderKind,
    ConsentScope,
    DecisionOutcome,
    DenialCode,
    HealthStatus,
    LifecycleState,
    Platform,
    PublishMode,
    ReviewState,
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------------------
class Capabilities(_Base):
    """What a platform adapter can do. Capabilities are *data* so the policy engine can reason
    about every platform uniformly."""

    platform: Platform
    publish_mode: PublishMode = PublishMode.API
    can_publish: bool = True
    can_comment: bool = True
    can_read: bool = True
    can_search: bool = True
    can_react: bool = False
    can_vote: bool = False  # e.g. Reddit up/down — distinct from react, and policy-blocked
    supports_media: bool = False
    requires_bot_flag: bool = False  # Mastodon
    self_label_supported: bool = False  # Bluesky
    max_text_len: int | None = None
    reaction_kinds: tuple[str, ...] = ()


class Persona(_Base):
    """Human-facing profile attributes of an account."""

    persona_label: str | None = None
    bio: str | None = None
    topic_scope: list[str] = Field(default_factory=list)
    # Domains the owner controls — drives the self-promotion classifier (Reddit 9:1).
    owned_domains: list[str] = Field(default_factory=list)
    voice_notes: str | None = None  # private guidance for drafting
    avatar_ref: str | None = None


class Authorization(_Base):
    """The master gate: consent to operate this account. No acting is permitted without it."""

    authorized: bool = False
    owner: str | None = None
    consent_scope: list[ConsentScope] = Field(default_factory=list)
    evidence_ref: str | None = None
    attested_by: str | None = None
    attested_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_effective(self) -> bool:
        return self.authorized and self.revoked_at is None

    def permits(self, scope: ConsentScope) -> bool:
        return self.is_effective() and scope in self.consent_scope


class LockLease(_Base):
    """A checkout lease so only one agent acts on an account at a time."""

    holder: str
    token: str
    acquired_at: datetime
    expires_at: datetime

    def is_active(self, at: datetime | None = None) -> bool:
        return (at or clock.now()) < self.expires_at

    def held_by(self, holder: str, token: str, at: datetime | None = None) -> bool:
        return self.is_active(at) and self.holder == holder and self.token == token


class HealthState(_Base):
    status: HealthStatus = HealthStatus.UNKNOWN
    last_health_at: datetime | None = None
    last_error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ComplianceMarkers(_Base):
    """Platform self-identification state (bot flag / self-label)."""

    bot_flag_set: bool = False
    self_label: str | None = None
    disclosure_profile: str | None = None


class TargetRef(_Base):
    """A reference to the thing an action targets (a post, thread, subreddit, feed, ...)."""

    raw: str  # url or platform id supplied by the agent
    platform: Platform | None = None
    kind: str | None = None  # submission / comment / subreddit / user (platform-specific)
    container: str | None = None  # subreddit / instance / community
    parent_id: str | None = None  # comment/post being replied to
    # Whether this target is a channel the pool owns (drives autonomy: own => auto, third-party
    # => approval). Defaults to False (safer): unknown targets are treated as third-party.
    is_owned: bool = False
    resolved: bool = False


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------
class Account(_Base):
    """The actor object."""

    account_id: str
    platform: Platform
    handle: str
    platform_user_id: str | None = None
    display_name: str | None = None
    profile_url: str | None = None

    persona: Persona = Field(default_factory=Persona)
    authorization: Authorization = Field(default_factory=Authorization)
    connection_id: str | None = None

    status: LifecycleState = LifecycleState.DRAFT
    requires_approval: bool = True  # default gate for third-party acts

    lock: LockLease | None = None
    record_version: int = 1  # optimistic concurrency

    rate_state: dict[str, Any] = Field(default_factory=dict)  # cached snapshot only
    health: HealthState = Field(default_factory=HealthState)
    capabilities: Capabilities | None = None  # cached from the adapter
    compliance: ComplianceMarkers = Field(default_factory=ComplianceMarkers)
    policy_overrides: dict[str, Any] = Field(default_factory=dict)

    tags: list[str] = Field(default_factory=list)
    pool: str | None = None

    created_at: datetime = Field(default_factory=clock.now)
    updated_at: datetime = Field(default_factory=clock.now)

    def is_active(self) -> bool:
        return self.status == LifecycleState.ACTIVE


class Connection(_Base):
    """Credential metadata. The secret material lives in the vault; only ``secret_ref`` is stored."""

    connection_id: str
    account_id: str
    platform: Platform
    auth_type: AuthType
    provider: ConnectionProviderKind = ConnectionProviderKind.BUILTIN
    scopes: list[str] = Field(default_factory=list)
    secret_ref: str
    expires_at: datetime | None = None
    refresh_ref: str | None = None
    created_at: datetime = Field(default_factory=clock.now)
    updated_at: datetime = Field(default_factory=clock.now)


class ContentDraft(_Base):
    """A draft is always allowed (no side effects). Editing bumps ``revision`` and invalidates any
    pinned approval."""

    draft_id: str
    account_id: str
    body: str
    # Title is required by some platforms (Reddit submissions, Medium posts); ignored by others.
    title: str | None = None
    media_refs: list[str] = Field(default_factory=list)
    disclosure: str | None = None
    revision: int = 1
    created_at: datetime = Field(default_factory=clock.now)
    updated_at: datetime = Field(default_factory=clock.now)


class DecisionStep(_Base):
    """One guard's verdict, accumulated into an action's decision trace."""

    guard: str
    outcome: DecisionOutcome
    denial_code: DenialCode | None = None
    message: str | None = None


class Action(_Base):
    """The act object an agent submits."""

    action_id: str
    account_id: str
    type: ActionType
    target: TargetRef | None = None
    draft_id: str | None = None
    react_kind: str | None = None  # for REACT actions (remembered across an approval round-trip)
    requested_by: str  # agent name (self-declared; coordination not security)
    idempotency_key: str | None = None
    state: ActionState = ActionState.PENDING
    decision_trace: list[DecisionStep] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    scheduled_for: datetime | None = None
    created_at: datetime = Field(default_factory=clock.now)
    updated_at: datetime = Field(default_factory=clock.now)


class ApprovalItem(_Base):
    """A queued approval for a third-party act (mirrors object_submit_review/object_review_decide)."""

    approval_id: str
    action_id: str
    account_id: str
    review_state: ReviewState = ReviewState.OPEN
    pinned_revision: int | None = None  # draft revision this approval is bound to
    summary: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=clock.now)
    expires_at: datetime | None = None  # open approvals past this are stale (cannot be approved)

    def is_expired(self, at: datetime | None = None) -> bool:
        return self.expires_at is not None and (at or clock.now()) > self.expires_at


class AuditEvent(_Base):
    """Append-only record. Written on every path: executed, refused, and approved."""

    event_id: str
    ts: datetime = Field(default_factory=clock.now)
    actor: str  # agent or human who caused the event
    verb: str
    outcome: DecisionOutcome
    account_id: str | None = None
    action_id: str | None = None
    denial_code: DenialCode | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    platform_result: dict[str, Any] | None = None
    policy_snapshot: dict[str, Any] | None = None
    message: str | None = None


class PlatformPolicy(_Base):
    """Per-platform policy configuration resolved by the guard pipeline."""

    platform: Platform
    publish_mode: PublishMode = PublishMode.API
    allowed_verbs: list[ActionType] = Field(default_factory=list)
    # action -> max writes per rolling window (see policy.ratelimit).
    rate_per_minute: dict[str, int] = Field(default_factory=dict)
    react_allowed: bool = False
    vote_allowed: bool = False  # always False in practice; Reddit voting is hard-blocked
    requires_bot_flag: bool = False
    requires_self_label: bool = False
    disclosure_required: bool = False
    # Reddit-style self-promotion ratio: at most 1 promo per N non-promo (0 disables).
    self_promo_ratio: int = 0
