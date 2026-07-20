"""A guard's verdict."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import DecisionOutcome, DenialCode


@dataclass(frozen=True)
class Decision:
    guard: str
    outcome: DecisionOutcome
    denial_code: DenialCode | None = None
    message: str | None = None


def allow(guard: str, message: str | None = None) -> Decision:
    return Decision(guard, DecisionOutcome.ALLOW, None, message)


def deny(guard: str, code: DenialCode, message: str | None = None) -> Decision:
    return Decision(guard, DecisionOutcome.DENY, code, message)


def route(
    guard: str,
    message: str | None = None,
    code: DenialCode = DenialCode.APPROVAL_REQUIRED,
) -> Decision:
    return Decision(guard, DecisionOutcome.ROUTE_TO_APPROVAL, code, message)
