"""Append-only audit writer.

Every acting path writes exactly one event — executed, refused, *and* approved. The
``policy_snapshot`` captures the guard decision trace so a refusal is fully explainable after the
fact.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..db.repositories import AuditRepository
from ..domain.enums import DecisionOutcome, DenialCode
from ..domain.ids import new_id
from ..domain.models import AuditEvent
from ..policy.decisions import Decision

_log = structlog.get_logger("account_pool.audit")


def trace_snapshot(trace: list[Decision]) -> dict[str, Any]:
    return {
        "trace": [
            {
                "guard": d.guard,
                "outcome": d.outcome.value,
                "denial_code": d.denial_code.value if d.denial_code else None,
                "message": d.message,
            }
            for d in trace
        ]
    }


class AuditLogger:
    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    def record(
        self,
        actor: str,
        verb: str,
        outcome: DecisionOutcome,
        *,
        account_id: str | None = None,
        action_id: str | None = None,
        denial_code: DenialCode | None = None,
        platform_result: dict[str, Any] | None = None,
        policy_snapshot: dict[str, Any] | None = None,
        message: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=new_id("evt"),
            actor=actor,
            verb=verb,
            outcome=outcome,
            account_id=account_id,
            action_id=action_id,
            denial_code=denial_code,
            platform_result=platform_result,
            policy_snapshot=policy_snapshot,
            message=message,
            before=before,
            after=after,
        )
        self._repo.append(event)
        _log.info(
            "audit",
            verb=verb,
            outcome=outcome.value,
            account_id=account_id,
            action_id=action_id,
            denial_code=denial_code.value if denial_code else None,
        )
        return event

    def query(
        self,
        account_id: str | None = None,
        action_id: str | None = None,
        verb: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        return self._repo.query(account_id=account_id, action_id=action_id, verb=verb, limit=limit)
