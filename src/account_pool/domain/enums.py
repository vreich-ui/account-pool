"""Enumerations shared across the domain, policy, and adapter layers."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """Supported (or planned) social platforms."""

    REDDIT = "reddit"
    MASTODON = "mastodon"
    BLUESKY = "bluesky"
    TWITTER = "twitter"
    MEDIUM = "medium"
    SUBSTACK = "substack"
    # Planned, behind partner/app-review gates:
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    THREADS = "threads"


class ActionType(StrEnum):
    """The verbs an agent can request an account perform ("acts")."""

    DRAFT = "draft"
    PUBLISH = "publish"
    COMMENT = "comment"
    READ = "read"
    MONITOR = "monitor"
    SEARCH = "search"
    REACT = "react"


# Verbs that mutate the outside world (require lock + full guard pipeline).
WRITE_ACTIONS: frozenset[ActionType] = frozenset({ActionType.PUBLISH, ActionType.COMMENT, ActionType.REACT})
# Verbs that only read (no lock required, lighter guard).
READ_ACTIONS: frozenset[ActionType] = frozenset({ActionType.READ, ActionType.MONITOR, ActionType.SEARCH})


class ConsentScope(StrEnum):
    """What an account's owner has authorized the pool to do on their behalf."""

    PUBLISH = "publish"
    COMMENT = "comment"
    REACT = "react"
    READ = "read"


# Which consent scope each action requires.
ACTION_CONSENT: dict[ActionType, ConsentScope] = {
    ActionType.PUBLISH: ConsentScope.PUBLISH,
    ActionType.COMMENT: ConsentScope.COMMENT,
    ActionType.REACT: ConsentScope.REACT,
    ActionType.READ: ConsentScope.READ,
    ActionType.MONITOR: ConsentScope.READ,
    ActionType.SEARCH: ConsentScope.READ,
}


class LifecycleState(StrEnum):
    """Account lifecycle. Only ACTIVE accounts may act."""

    DRAFT = "draft"  # registered, not yet connected
    CONNECTED = "connected"  # credentials present, not yet authorized/active
    ACTIVE = "active"  # authorized + connected; may act
    SUSPENDED = "suspended"  # temporarily withheld
    RETIRED = "retired"  # soft-deleted


class ActionState(StrEnum):
    """Lifecycle of an Action object."""

    PENDING = "pending"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"
    REFUSED = "refused"  # blocked by policy


class ReviewState(StrEnum):
    """Review state of an ApprovalItem (mirrors the Dr_Lurie object system)."""

    OPEN = "open"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


class PublishMode(StrEnum):
    """How real a platform's write path is."""

    API = "api"  # real writes via official API
    DRAFT_ONLY = "draft_only"  # can only stage drafts (e.g. Medium for new apps)
    MANUAL = "manual"  # no automated write path at all (e.g. Substack)


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    REAUTH_NEEDED = "reauth_needed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class AuthType(StrEnum):
    OAUTH2 = "oauth2"
    APP_PASSWORD = "app_password"
    API_KEY = "api_key"


class ConnectionProviderKind(StrEnum):
    BUILTIN = "builtin"
    NANGO = "nango"
    COMPOSIO = "composio"


class DecisionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ROUTE_TO_APPROVAL = "route_to_approval"


class DenialCode(StrEnum):
    """Fixed catalog of refusal reasons (mirrors the Dr_Lurie denial_codes pattern)."""

    NOT_AUTHORIZED = "not_authorized"
    ACCOUNT_NOT_ACTIVE = "account_not_active"
    LOCK_REQUIRED = "lock_required"
    LOCK_HELD_BY_OTHER = "lock_held_by_other"
    VERSION_CONFLICT = "version_conflict"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    PUBLISH_MODE_MANUAL = "publish_mode_manual"
    RATE_LIMITED = "rate_limited"
    SELF_PROMO_RATIO = "self_promo_ratio"
    SUBREDDIT_RULE = "subreddit_rule"
    BOT_IDENTIFICATION_REQUIRED = "bot_identification_required"
    VOTE_MANIPULATION_BLOCKED = "vote_manipulation_blocked"
    COORDINATION_BLOCKED = "coordination_blocked"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_STALE = "approval_stale"
    CONTENT_INVALID = "content_invalid"
    TARGET_INVALID = "target_invalid"


# HTTP-status parity for callers that prefer codes (423 lock, 409 conflict, ...).
DENIAL_HTTP_STATUS: dict[DenialCode, int] = {
    DenialCode.NOT_AUTHORIZED: 403,
    DenialCode.ACCOUNT_NOT_ACTIVE: 409,
    DenialCode.LOCK_REQUIRED: 423,
    DenialCode.LOCK_HELD_BY_OTHER: 423,
    DenialCode.VERSION_CONFLICT: 409,
    DenialCode.CAPABILITY_UNSUPPORTED: 422,
    DenialCode.PUBLISH_MODE_MANUAL: 422,
    DenialCode.RATE_LIMITED: 429,
    DenialCode.SELF_PROMO_RATIO: 429,
    DenialCode.SUBREDDIT_RULE: 422,
    DenialCode.BOT_IDENTIFICATION_REQUIRED: 412,
    DenialCode.VOTE_MANIPULATION_BLOCKED: 403,
    DenialCode.COORDINATION_BLOCKED: 429,
    DenialCode.APPROVAL_REQUIRED: 202,
    DenialCode.APPROVAL_STALE: 409,
    DenialCode.CONTENT_INVALID: 422,
    DenialCode.TARGET_INVALID: 422,
}
