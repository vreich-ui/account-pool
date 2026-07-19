"""Inputs and outputs of the guard pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.enums import WRITE_ACTIONS, ActionType, DecisionOutcome, DenialCode
from ..domain.models import Account, Capabilities, ContentDraft, PlatformPolicy, TargetRef
from .decisions import Decision
from .ratelimit import RateLimiter
from .trackers import CoordinationTracker, SelfPromoLedger


@dataclass
class GuardContext:
    """Everything the guards need to evaluate one acting request."""

    account: Account
    action_type: ActionType
    capabilities: Capabilities
    policy: PlatformPolicy
    caller: str
    rate_limiter: RateLimiter
    coordination: CoordinationTracker
    promo_ledger: SelfPromoLedger
    lock_token: str | None = None
    draft: ContentDraft | None = None
    target: TargetRef | None = None
    react_kind: str | None = None

    @property
    def is_write(self) -> bool:
        return self.action_type in WRITE_ACTIONS

    @property
    def target_key(self) -> str:
        if self.target is None:
            return ""
        return f"{self.account.platform.value}:{self.target.raw}"

    @property
    def is_owned_target(self) -> bool:
        # Publishing to one's own channel has no third-party target; treat as owned.
        if self.action_type == ActionType.PUBLISH:
            return True
        return bool(self.target and self.target.is_owned)


@dataclass
class PolicyResult:
    outcome: DecisionOutcome
    decision: Decision
    trace: list[Decision] = field(default_factory=list)

    @property
    def is_allow(self) -> bool:
        return self.outcome == DecisionOutcome.ALLOW

    @property
    def is_deny(self) -> bool:
        return self.outcome == DecisionOutcome.DENY

    @property
    def is_route(self) -> bool:
        return self.outcome == DecisionOutcome.ROUTE_TO_APPROVAL

    @property
    def denial_code(self) -> DenialCode | None:
        return self.decision.denial_code
