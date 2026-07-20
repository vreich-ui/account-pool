"""Platform support tiers — an honest, at-a-glance view of what the pool can actually do per
platform, used by the admin UI's breadth grid.

Tiers:
* ``live``       — a real API adapter with automated read + write.
* ``draft_only`` — can stage a draft; never makes a live post (Medium).
* ``manual``     — read-only + manual export; no automated write (Substack).
* ``planned``    — known to the model but not yet wired to a real adapter.
"""

from __future__ import annotations

from typing import Any

from .adapters.registry import real_adapter_platforms
from .domain.enums import Platform, PublishMode
from .policy.policies import get_platform_policy

_TIER_ORDER = {"live": 0, "draft_only": 1, "manual": 2, "planned": 3}


def support_tier(platform: Platform) -> str:
    real = platform in real_adapter_platforms()
    policy = get_platform_policy(platform)
    if real and policy.publish_mode == PublishMode.API:
        return "live"
    if policy.publish_mode == PublishMode.DRAFT_ONLY:
        return "draft_only"
    if real and policy.publish_mode == PublishMode.MANUAL:
        return "manual"
    return "planned"


def platform_overview() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for platform in Platform:
        policy = get_platform_policy(platform)
        rows.append(
            {
                "platform": platform.value,
                "tier": support_tier(platform),
                "publish_mode": policy.publish_mode.value,
                "verbs": [v.value for v in policy.allowed_verbs],
                "react_allowed": policy.react_allowed,
                "requires_bot_flag": policy.requires_bot_flag,
                "requires_self_label": policy.requires_self_label,
                "self_promo_ratio": policy.self_promo_ratio,
            }
        )
    rows.sort(key=lambda r: (_TIER_ORDER.get(r["tier"], 9), r["platform"]))
    return rows
