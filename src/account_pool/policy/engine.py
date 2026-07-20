"""The guard pipeline orchestrator.

Runs guards in order, accumulating a decision trace, and short-circuits on the first DENY or ROUTE.
This is the single choke point every acting request passes through before an adapter is touched.
"""

from __future__ import annotations

from ..domain.enums import DecisionOutcome
from .context import GuardContext, PolicyResult
from .decisions import Decision, allow
from .guards import DEFAULT_GUARDS, Guard


class PolicyEngine:
    def __init__(self, guards: list[Guard] | None = None) -> None:
        self._guards: list[Guard] = guards if guards is not None else DEFAULT_GUARDS

    def evaluate(self, ctx: GuardContext) -> PolicyResult:
        trace: list[Decision] = []
        for guard in self._guards:
            decision = guard.evaluate(ctx)
            trace.append(decision)
            if decision.outcome == DecisionOutcome.DENY:
                return PolicyResult(DecisionOutcome.DENY, decision, trace)
            if decision.outcome == DecisionOutcome.ROUTE_TO_APPROVAL:
                return PolicyResult(DecisionOutcome.ROUTE_TO_APPROVAL, decision, trace)
        final = allow("engine")
        return PolicyResult(DecisionOutcome.ALLOW, final, trace)
