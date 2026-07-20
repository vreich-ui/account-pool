"""Default per-platform policy and override resolution.

Overrides on an account may only *tighten* (lower rate limits, force approval, require a bot flag),
never relax below these baselines — mirroring the server-enforced, non-patchable publish gate in the
CMS-Agent contract.
"""

from __future__ import annotations

from ..domain.enums import ActionType, Platform, PublishMode
from ..domain.models import Account, PlatformPolicy

_READ_VERBS = [ActionType.READ, ActionType.MONITOR, ActionType.SEARCH]

_DEFAULTS: dict[Platform, PlatformPolicy] = {
    Platform.REDDIT: PlatformPolicy(
        platform=Platform.REDDIT,
        publish_mode=PublishMode.API,
        allowed_verbs=[ActionType.PUBLISH, ActionType.COMMENT, *_READ_VERBS],
        rate_per_minute={"publish": 1, "comment": 3, "read": 30, "monitor": 30, "search": 10},
        react_allowed=False,  # up/down voting is not offered as an automated action
        vote_allowed=False,  # and is hard-blocked in the manipulation guard
        self_promo_ratio=9,  # ~90/10 guideline
    ),
    Platform.MASTODON: PlatformPolicy(
        platform=Platform.MASTODON,
        publish_mode=PublishMode.API,
        allowed_verbs=[ActionType.PUBLISH, ActionType.COMMENT, ActionType.REACT, *_READ_VERBS],
        rate_per_minute={"publish": 5, "comment": 10, "react": 20, "read": 60, "search": 30},
        react_allowed=True,
        requires_bot_flag=True,
    ),
    Platform.BLUESKY: PlatformPolicy(
        platform=Platform.BLUESKY,
        publish_mode=PublishMode.API,
        allowed_verbs=[ActionType.PUBLISH, ActionType.COMMENT, ActionType.REACT, *_READ_VERBS],
        rate_per_minute={"publish": 5, "comment": 10, "react": 20, "read": 60, "search": 30},
        react_allowed=True,
        requires_self_label=True,
    ),
    Platform.TWITTER: PlatformPolicy(
        platform=Platform.TWITTER,
        publish_mode=PublishMode.API,
        allowed_verbs=[ActionType.PUBLISH, ActionType.COMMENT, ActionType.REACT, *_READ_VERBS],
        rate_per_minute={"publish": 3, "comment": 5, "react": 10, "read": 15, "search": 10},
        react_allowed=True,
    ),
    Platform.MEDIUM: PlatformPolicy(
        platform=Platform.MEDIUM,
        publish_mode=PublishMode.DRAFT_ONLY,  # tokens frozen for new apps -> draft/manual
        allowed_verbs=[ActionType.PUBLISH, ActionType.READ],
        rate_per_minute={"publish": 2, "read": 20},
    ),
    Platform.SUBSTACK: PlatformPolicy(
        platform=Platform.SUBSTACK,
        publish_mode=PublishMode.MANUAL,  # no official API -> manual assist + RSS read only
        allowed_verbs=[ActionType.PUBLISH, ActionType.READ],
        rate_per_minute={"publish": 1, "read": 20},
    ),
}


def get_platform_policy(platform: Platform) -> PlatformPolicy:
    """Baseline policy for a platform. Platforms without an explicit entry get a safe, minimal
    default (draft-only, reads only)."""
    if platform in _DEFAULTS:
        return _DEFAULTS[platform].model_copy(deep=True)
    return PlatformPolicy(
        platform=platform,
        publish_mode=PublishMode.MANUAL,
        allowed_verbs=list(_READ_VERBS),
        rate_per_minute={"read": 20},
    )


def resolve_policy(account: Account) -> PlatformPolicy:
    """Baseline policy tightened (never loosened) by an account's ``policy_overrides``."""
    policy = get_platform_policy(account.platform)
    overrides = account.policy_overrides or {}

    # Rate limits may only be lowered.
    for verb, limit in (overrides.get("rate_per_minute") or {}).items():
        current = policy.rate_per_minute.get(verb)
        policy.rate_per_minute[verb] = min(current, limit) if current is not None else limit

    # Bot-flag / self-label requirements may be added, never removed.
    if overrides.get("requires_bot_flag"):
        policy.requires_bot_flag = True
    if overrides.get("requires_self_label"):
        policy.requires_self_label = True

    # Self-promo ratio may only be made stricter (larger N).
    ov_ratio = overrides.get("self_promo_ratio")
    if isinstance(ov_ratio, int) and ov_ratio > policy.self_promo_ratio:
        policy.self_promo_ratio = ov_ratio

    return policy
