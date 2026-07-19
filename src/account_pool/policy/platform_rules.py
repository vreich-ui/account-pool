"""Platform-specific content rules (currently Reddit's self-promo ratio + subreddit-rule hook).

These are heuristics that pair with the approval gate — nuanced subreddit rules still route to human
review rather than being auto-approved.
"""

from __future__ import annotations

from ..domain.enums import DenialCode, Platform
from .context import GuardContext
from .decisions import Decision, allow, deny
from .trackers import is_promotional

# Subreddits/communities the operator has flagged as off-limits (hook; empty by default).
BLOCKED_CONTAINERS: set[str] = set()


def evaluate_platform_rules(ctx: GuardContext) -> Decision:
    guard = "platform_rules"
    if ctx.account.platform == Platform.REDDIT:
        return _reddit_rules(ctx, guard)
    return allow(guard)


def _reddit_rules(ctx: GuardContext, guard: str) -> Decision:
    # Subreddit rule hook: block explicitly disallowed containers.
    if ctx.target and ctx.target.container and ctx.target.container in BLOCKED_CONTAINERS:
        return deny(
            guard,
            DenialCode.SUBREDDIT_RULE,
            f"container '{ctx.target.container}' is on the block list",
        )

    # Self-promotion ratio (~90/10). Applies to promotional drafts only.
    if ctx.draft and is_promotional(ctx.draft, ctx.account):
        if ctx.promo_ledger.would_exceed(ctx.account.account_id, ctx.policy.self_promo_ratio):
            promo, non_promo = ctx.promo_ledger.counts(ctx.account.account_id)
            return deny(
                guard,
                DenialCode.SELF_PROMO_RATIO,
                f"self-promo ratio {ctx.policy.self_promo_ratio}:1 would be exceeded "
                f"(promo={promo}, non_promo={non_promo})",
            )
    return allow(guard)
