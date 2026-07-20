"""The policy guard pipeline — where every compliance boundary is enforced.

No acting call reaches an adapter except through :class:`~account_pool.policy.engine.PolicyEngine`.
"""

from .context import GuardContext, PolicyResult
from .decisions import Decision, allow, deny, route
from .engine import PolicyEngine
from .policies import get_platform_policy, resolve_policy
from .ratelimit import RateLimiter
from .trackers import CoordinationTracker, SelfPromoLedger, is_promotional

__all__ = [
    "PolicyEngine",
    "GuardContext",
    "PolicyResult",
    "Decision",
    "allow",
    "deny",
    "route",
    "RateLimiter",
    "CoordinationTracker",
    "SelfPromoLedger",
    "is_promotional",
    "get_platform_policy",
    "resolve_policy",
]
