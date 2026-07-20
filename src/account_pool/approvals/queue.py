"""Approval queue — thin data layer over ApprovalRepository.

Execution of an approved item is orchestrated by the actions service (which re-checks safety and
draft staleness), keeping this module free of adapter/policy dependencies.
"""

from __future__ import annotations

from .. import clock
from ..db.repositories import ApprovalRepository
from ..domain.enums import ReviewState
from ..domain.ids import new_id
from ..domain.models import Action, ApprovalItem


class ApprovalQueue:
    def __init__(self, repo: ApprovalRepository) -> None:
        self._repo = repo

    def submit(self, action: Action, summary: str | None, pinned_revision: int | None) -> ApprovalItem:
        approval = ApprovalItem(
            approval_id=new_id("appr"),
            action_id=action.action_id,
            account_id=action.account_id,
            review_state=ReviewState.OPEN,
            pinned_revision=pinned_revision,
            summary=summary,
        )
        return self._repo.upsert(approval)

    def get(self, approval_id: str) -> ApprovalItem | None:
        return self._repo.get(approval_id)

    def list_open(self) -> list[ApprovalItem]:
        return self._repo.list(review_state=ReviewState.OPEN.value)

    def set_state(
        self,
        approval: ApprovalItem,
        state: ReviewState,
        decided_by: str | None = None,
        reason: str | None = None,
    ) -> ApprovalItem:
        approval.review_state = state
        if decided_by is not None:
            approval.decided_by = decided_by
            approval.decided_at = clock.now()
        if reason is not None:
            approval.reason = reason
        return self._repo.upsert(approval)
