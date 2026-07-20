"""Self-describing contracts ("read first"), mirroring the Dr_Lurie object_contract pattern.

The MCP ``account_contract`` tool and ``contract://account/{platform}`` resource return these so an
agent can discover the object lifecycle, the allowed verbs, and the denial codes *before* acting.
"""

from __future__ import annotations

from typing import Any

from .enums import (
    ACTION_CONSENT,
    DENIAL_HTTP_STATUS,
    ActionState,
    ActionType,
    ConsentScope,
    DenialCode,
    LifecycleState,
)
from .models import Capabilities, PlatformPolicy

_DENIAL_MEANINGS: dict[DenialCode, str] = {
    DenialCode.NOT_AUTHORIZED: "Account lacks an effective authorization for this consent scope.",
    DenialCode.ACCOUNT_NOT_ACTIVE: "Account is not in the ACTIVE lifecycle state.",
    DenialCode.LOCK_REQUIRED: "A write requires the account to be checked out (locked) first.",
    DenialCode.LOCK_HELD_BY_OTHER: "The account is currently checked out by another agent.",
    DenialCode.VERSION_CONFLICT: "The account changed since you read it (optimistic-lock clash).",
    DenialCode.CAPABILITY_UNSUPPORTED: "This platform adapter does not support the requested verb.",
    DenialCode.PUBLISH_MODE_MANUAL: "This platform is draft-only/manual; no automated write path.",
    DenialCode.RATE_LIMITED: "Per-account rate limit for this verb has been exhausted.",
    DenialCode.SELF_PROMO_RATIO: "Would exceed the platform's self-promotion ratio.",
    DenialCode.SUBREDDIT_RULE: "Blocked by a subreddit/community rule check.",
    DenialCode.BOT_IDENTIFICATION_REQUIRED: "Account must self-identify as automated first.",
    DenialCode.VOTE_MANIPULATION_BLOCKED: "Voting is hard-blocked to prevent manipulation.",
    DenialCode.COORDINATION_BLOCKED: "Multiple pool accounts targeting one item (coordination).",
    DenialCode.APPROVAL_REQUIRED: "Queued for human approval before it can execute.",
    DenialCode.APPROVAL_STALE: "The draft changed after approval; re-approval required.",
    DenialCode.CONTENT_INVALID: "Draft content failed validation (length/media/format).",
    DenialCode.TARGET_INVALID: "The target reference could not be resolved.",
}


def denial_code_catalog() -> list[dict[str, Any]]:
    return [
        {
            "code": code.value,
            "http_status": DENIAL_HTTP_STATUS[code],
            "meaning": _DENIAL_MEANINGS[code],
        }
        for code in DenialCode
    ]


def account_lifecycle_contract() -> dict[str, Any]:
    return {
        "states": [s.value for s in LifecycleState],
        "transitions": {
            "register": f"{LifecycleState.DRAFT.value}",
            "connect": f"{LifecycleState.DRAFT.value} -> {LifecycleState.CONNECTED.value}",
            "authorize": f"{LifecycleState.CONNECTED.value} -> {LifecycleState.ACTIVE.value}",
            "retire": f"* -> {LifecycleState.RETIRED.value}",
        },
        "concurrency": {
            "lock": "Acquire a lease via account_checkout; writes require it (else lock_required).",
            "version": "account_patch is optimistic — pass expected_record_version (else conflict).",
        },
        "only_active_may_act": True,
    }


def action_lifecycle_contract() -> dict[str, Any]:
    return {
        "states": [s.value for s in ActionState],
        "flow": "draft -> validate -> (approval) -> execute -> audit",
        "consent_required": {a.value: ACTION_CONSENT[a].value for a in ACTION_CONSENT},
    }


def build_account_contract(
    capabilities: Capabilities,
    policy: PlatformPolicy,
) -> dict[str, Any]:
    """Compose the full read-first contract for one platform."""
    return {
        "platform": capabilities.platform.value,
        "publish_mode": policy.publish_mode.value,
        "capabilities": capabilities.model_dump(mode="json"),
        "policy": {
            "allowed_verbs": [v.value for v in policy.allowed_verbs],
            "rate_per_minute": policy.rate_per_minute,
            "react_allowed": policy.react_allowed,
            "vote_allowed": policy.vote_allowed,
            "requires_bot_flag": policy.requires_bot_flag,
            "requires_self_label": policy.requires_self_label,
            "disclosure_required": policy.disclosure_required,
            "self_promo_ratio": policy.self_promo_ratio,
        },
        "consent_scopes": [c.value for c in ConsentScope],
        "account_lifecycle": account_lifecycle_contract(),
        "action_lifecycle": action_lifecycle_contract(),
        "denial_codes": denial_code_catalog(),
        "verbs": [v.value for v in ActionType],
        "boundaries": {
            "authorized_accounts_only": True,
            "official_apis_only": True,
            "no_account_generation": True,
            "no_evasion_or_scraping": True,
            "vote_manipulation": "hard-blocked",
            "coordination": "detected and blocked/queued",
        },
    }
