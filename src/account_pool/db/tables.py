"""ORM tables.

Hybrid layout: a few typed, indexed columns for querying + a JSON ``data`` column holding the full
pydantic payload. This keeps the domain model authoritative (pydantic) while staying queryable and
portable from SQLite to Postgres. **No secret material is stored here** — connections keep only a
``secret_ref`` pointer.
"""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, index=True)
    handle: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pool: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lock_holder: Mapped[str | None] = mapped_column(String, nullable=True)
    lock_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSON)


class ConnectionRow(Base):
    __tablename__ = "connections"

    connection_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    platform: Mapped[str] = mapped_column(String, index=True)
    updated_at: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


class DraftRow(Base):
    __tablename__ = "drafts"

    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


class ActionRow(Base):
    __tablename__ = "actions"

    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    type: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    updated_at: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSON)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    review_state: Mapped[str] = mapped_column(String, index=True)
    updated_at: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSON)


class AuditRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    verb: Mapped[str] = mapped_column(String, index=True)
    outcome: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSON)
