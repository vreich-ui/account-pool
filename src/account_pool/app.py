"""Composition root: wire repositories, services, vault, and policy into one container.

Both the MCP server and the tests build an :class:`AppContext` from here so wiring lives in exactly
one place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .accounts.service import AccountService
from .actions.locking import LockService
from .actions.service import ActionService
from .adapters.registry import AdapterRegistry, build_registry
from .approvals.queue import ApprovalQueue
from .audit.log import AuditLogger
from .config import Settings, get_settings
from .db.engine import Database
from .db.repositories import (
    AccountRepository,
    ActionRepository,
    ApprovalRepository,
    AuditRepository,
    ConnectionRepository,
    DraftRepository,
)
from .domain.models import Account, ApprovalItem
from .policy.engine import PolicyEngine
from .policy.ratelimit import RateLimiter
from .policy.trackers import CoordinationTracker, SelfPromoLedger
from .vault.keyref import resolve_master_key
from .vault.provider import BuiltinConnectionProvider, ConnectionProvider
from .vault.vault import EncryptedVault


@dataclass
class AppContext:
    settings: Settings
    db: Database
    vault: EncryptedVault
    provider: ConnectionProvider
    registry: AdapterRegistry
    engine: PolicyEngine
    rate_limiter: RateLimiter
    coordination: CoordinationTracker
    promo_ledger: SelfPromoLedger
    audit: AuditLogger
    approvals: ApprovalQueue
    lock_service: LockService
    account_service: AccountService
    action_service: ActionService


def build_app(
    settings: Settings | None = None,
    *,
    registry: AdapterRegistry | None = None,
    vault: EncryptedVault | None = None,
    notifier: Callable[[ApprovalItem, Account], None] | None = None,
) -> AppContext:
    settings = settings or get_settings()

    db = Database(settings.database_url)
    db.create_all()

    if vault is None:
        vault = EncryptedVault(resolve_master_key(settings), settings.vault_path)
    provider: ConnectionProvider = BuiltinConnectionProvider(vault)
    registry = registry or build_registry(settings.real_adapters_list)
    engine = PolicyEngine()
    rate_limiter = RateLimiter()
    coordination = CoordinationTracker()
    promo_ledger = SelfPromoLedger()

    accounts_repo = AccountRepository(db)
    connections_repo = ConnectionRepository(db)
    drafts_repo = DraftRepository(db)
    actions_repo = ActionRepository(db)
    approval_repo = ApprovalRepository(db)
    audit_repo = AuditRepository(db)

    audit = AuditLogger(audit_repo)
    approvals = ApprovalQueue(approval_repo, ttl_seconds=settings.approval_ttl_seconds)
    lock_service = LockService(accounts_repo, settings.default_lock_ttl_seconds)
    account_service = AccountService(accounts_repo, connections_repo, registry, provider, audit)
    action_service = ActionService(
        accounts=accounts_repo,
        connections=connections_repo,
        drafts=drafts_repo,
        actions=actions_repo,
        approvals=approvals,
        audit=audit,
        registry=registry,
        provider=provider,
        engine=engine,
        rate_limiter=rate_limiter,
        coordination=coordination,
        promo_ledger=promo_ledger,
        settings=settings,
        notifier=notifier,
    )

    return AppContext(
        settings=settings,
        db=db,
        vault=vault,
        provider=provider,
        registry=registry,
        engine=engine,
        rate_limiter=rate_limiter,
        coordination=coordination,
        promo_ledger=promo_ledger,
        audit=audit,
        approvals=approvals,
        lock_service=lock_service,
        account_service=account_service,
        action_service=action_service,
    )
