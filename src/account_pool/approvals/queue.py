"""Approval queue — thin data layer over ApprovalRepository.

Execution of an approved item is orchestrated by the actions service (which re-checks safety and
draft staleness), keeping this module free of adapter/policy dependencies.
"""

from __future__ import annotations

from datetime import timedelta

from .. import clock
from ..config import get_settings
from ..db.repositories import ApprovalRepository
from ..domain.enums import ReviewState
from ..domain.ids import new_id
from ..domain.models import Action, ApprovalItem


class ApprovalQueue:
    def __init__(self, repo: ApprovalRepository, ttl_seconds: int | None = None) -> None:
        self._repo = repo
        self._ttl = ttl_seconds if ttl_seconds is not None else get_settings().approval_ttl_seconds

    def submit(self, action: Action, summary: str | None, pinned_revision: int | None) -> ApprovalItem:
        now = clock.now()
        approval = ApprovalItem(
            approval_id=new_id("appr"),
            action_id=action.action_id,
            account_id=action.account_id,
            review_state=ReviewState.OPEN,
            pinned_revision=pinned_revision,
            summary=summary,
            expires_at=now + timedelta(seconds=self._ttl) if self._ttl > 0 else None,
        )
        return self._repo.upsert(approval)

    def get(self, approval_id: str) -> ApprovalItem | None:
        return self._repo.get(approval_id)

    def list_open(
        self, platform: str | None = None, account_id: str | None = None, include_expired: bool = True
    ) -> list[ApprovalItem]:
        items = self._repo.list(review_state=ReviewState.OPEN.value)
        if account_id is not None:
            items = [i for i in items if i.account_id == account_id]
        if platform is not None:
            items = [i for i in items if i.account_id.startswith(f"acct_{platform}_")]
        if not include_expired:
            items = [i for i in items if not i.is_expired()]
        return items

    def reopen(self, approval: ApprovalItem, pinned_revision: int | None) -> ApprovalItem:
        """Re-open a changes-requested approval against the latest draft revision, refreshing TTL."""
        approval.review_state = ReviewState.OPEN
        approval.pinned_revision = pinned_revision
        approval.decided_by = None
        approval.decided_at = None
        approval.reason = None
        approval.expires_at = clock.now() + timedelta(seconds=self._ttl) if self._ttl > 0 else None
        return self._repo.upsert(approval)

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
