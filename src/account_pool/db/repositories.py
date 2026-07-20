"""Repositories: translate between pydantic domain objects and rows.

The only subtle one is :meth:`AccountRepository.update`, which performs an **atomic conditional
update** on ``record_version`` — this is what makes checkout (lock acquisition) and patch race-free
(a stale writer gets :class:`VersionConflict`).
"""

from __future__ import annotations

from sqlalchemy import select, update

from .. import clock
from ..domain.enums import Platform
from ..domain.models import (
    Account,
    Action,
    ApprovalItem,
    AuditEvent,
    Connection,
    ContentDraft,
)
from .engine import Database
from .tables import (
    AccountRow,
    ActionRow,
    ApprovalRow,
    AuditRow,
    ConnectionRow,
    DraftRow,
)


class VersionConflict(RuntimeError):
    """Raised when an optimistic update loses the record_version race."""


def _lock_fields(account: Account) -> tuple[str | None, str | None]:
    if account.lock is None:
        return None, None
    return account.lock.holder, account.lock.expires_at.isoformat()


class AccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, account: Account) -> Account:
        holder, expires = _lock_fields(account)
        with self._db.session() as s:
            s.add(
                AccountRow(
                    account_id=account.account_id,
                    platform=account.platform.value,
                    handle=account.handle,
                    status=account.status.value,
                    record_version=account.record_version,
                    pool=account.pool,
                    lock_holder=holder,
                    lock_expires_at=expires,
                    updated_at=account.updated_at.isoformat(),
                    data=account.model_dump(mode="json"),
                )
            )
        return account

    def get(self, account_id: str) -> Account | None:
        with self._db.session() as s:
            row = s.get(AccountRow, account_id)
            return Account.model_validate(row.data) if row else None

    def list(
        self,
        platform: Platform | None = None,
        status: str | None = None,
        pool: str | None = None,
        tag: str | None = None,
    ) -> list[Account]:
        stmt = select(AccountRow)
        if platform is not None:
            stmt = stmt.where(AccountRow.platform == platform.value)
        if status is not None:
            stmt = stmt.where(AccountRow.status == status)
        if pool is not None:
            stmt = stmt.where(AccountRow.pool == pool)
        with self._db.session() as s:
            rows = s.execute(stmt).scalars().all()
        accounts = [Account.model_validate(r.data) for r in rows]
        if tag is not None:
            accounts = [a for a in accounts if tag in a.tags]
        return accounts

    def update(self, account: Account, expected_version: int) -> Account:
        """Persist ``account`` iff the stored record_version still equals ``expected_version``.

        Bumps the version to ``expected_version + 1`` on success. Raises :class:`VersionConflict`
        on a stale write and ``KeyError`` if the account no longer exists.
        """
        new_version = expected_version + 1
        account.record_version = new_version
        account.updated_at = clock.now()
        holder, expires = _lock_fields(account)
        with self._db.session() as s:
            result = s.execute(
                update(AccountRow)
                .where(
                    AccountRow.account_id == account.account_id,
                    AccountRow.record_version == expected_version,
                )
                .values(
                    platform=account.platform.value,
                    handle=account.handle,
                    status=account.status.value,
                    record_version=new_version,
                    pool=account.pool,
                    lock_holder=holder,
                    lock_expires_at=expires,
                    updated_at=account.updated_at.isoformat(),
                    data=account.model_dump(mode="json"),
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                exists = s.get(AccountRow, account.account_id) is not None
                if not exists:
                    raise KeyError(account.account_id)
                raise VersionConflict(f"{account.account_id}: expected version {expected_version}")
        return account


class ConnectionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, connection: Connection) -> Connection:
        with self._db.session() as s:
            s.add(
                ConnectionRow(
                    connection_id=connection.connection_id,
                    account_id=connection.account_id,
                    platform=connection.platform.value,
                    updated_at=connection.updated_at.isoformat(),
                    data=connection.model_dump(mode="json"),
                )
            )
        return connection

    def get(self, connection_id: str) -> Connection | None:
        with self._db.session() as s:
            row = s.get(ConnectionRow, connection_id)
            return Connection.model_validate(row.data) if row else None


class DraftRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, draft: ContentDraft) -> ContentDraft:
        with self._db.session() as s:
            row = s.get(DraftRow, draft.draft_id)
            if row is None:
                s.add(
                    DraftRow(
                        draft_id=draft.draft_id,
                        account_id=draft.account_id,
                        revision=draft.revision,
                        updated_at=draft.updated_at.isoformat(),
                        data=draft.model_dump(mode="json"),
                    )
                )
            else:
                row.revision = draft.revision
                row.updated_at = draft.updated_at.isoformat()
                row.data = draft.model_dump(mode="json")
        return draft

    def get(self, draft_id: str) -> ContentDraft | None:
        with self._db.session() as s:
            row = s.get(DraftRow, draft_id)
            return ContentDraft.model_validate(row.data) if row else None


class ActionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, action: Action) -> Action:
        with self._db.session() as s:
            row = s.get(ActionRow, action.action_id)
            payload = action.model_dump(mode="json")
            if row is None:
                s.add(
                    ActionRow(
                        action_id=action.action_id,
                        account_id=action.account_id,
                        type=action.type.value,
                        state=action.state.value,
                        idempotency_key=action.idempotency_key,
                        updated_at=action.updated_at.isoformat(),
                        data=payload,
                    )
                )
            else:
                row.state = action.state.value
                row.updated_at = action.updated_at.isoformat()
                row.data = payload
        return action

    def get(self, action_id: str) -> Action | None:
        with self._db.session() as s:
            row = s.get(ActionRow, action_id)
            return Action.model_validate(row.data) if row else None

    def find_by_idempotency_key(self, key: str) -> Action | None:
        with self._db.session() as s:
            row = s.execute(select(ActionRow).where(ActionRow.idempotency_key == key)).scalars().first()
            return Action.model_validate(row.data) if row else None


class ApprovalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, approval: ApprovalItem) -> ApprovalItem:
        with self._db.session() as s:
            row = s.get(ApprovalRow, approval.approval_id)
            payload = approval.model_dump(mode="json")
            if row is None:
                s.add(
                    ApprovalRow(
                        approval_id=approval.approval_id,
                        action_id=approval.action_id,
                        account_id=approval.account_id,
                        review_state=approval.review_state.value,
                        updated_at=clock.now().isoformat(),
                        data=payload,
                    )
                )
            else:
                row.review_state = approval.review_state.value
                row.updated_at = clock.now().isoformat()
                row.data = payload
        return approval

    def get(self, approval_id: str) -> ApprovalItem | None:
        with self._db.session() as s:
            row = s.get(ApprovalRow, approval_id)
            return ApprovalItem.model_validate(row.data) if row else None

    def list(self, review_state: str | None = None) -> list[ApprovalItem]:
        stmt = select(ApprovalRow)
        if review_state is not None:
            stmt = stmt.where(ApprovalRow.review_state == review_state)
        stmt = stmt.order_by(ApprovalRow.updated_at)
        with self._db.session() as s:
            rows = s.execute(stmt).scalars().all()
            return [ApprovalItem.model_validate(r.data) for r in rows]


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._db.session() as s:
            s.add(
                AuditRow(
                    event_id=event.event_id,
                    ts=event.ts.isoformat(),
                    account_id=event.account_id,
                    action_id=event.action_id,
                    verb=event.verb,
                    outcome=event.outcome.value,
                    data=event.model_dump(mode="json"),
                )
            )
        return event

    def query(
        self,
        account_id: str | None = None,
        action_id: str | None = None,
        verb: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        stmt = select(AuditRow)
        if account_id is not None:
            stmt = stmt.where(AuditRow.account_id == account_id)
        if action_id is not None:
            stmt = stmt.where(AuditRow.action_id == action_id)
        if verb is not None:
            stmt = stmt.where(AuditRow.verb == verb)
        stmt = stmt.order_by(AuditRow.ts.desc()).limit(limit)
        with self._db.session() as s:
            rows = s.execute(stmt).scalars().all()
            return [AuditEvent.model_validate(r.data) for r in rows]
