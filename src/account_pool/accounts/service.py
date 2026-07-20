"""Account lifecycle — the verbs that *act upon* an account.

Registration/authorization/connection/retirement are administrative and use optimistic-version
writes; ``patch`` (mutating an active account's persona/policy) additionally requires the caller to
hold the checkout lock. Only an account that is both **connected** and **authorized** becomes ACTIVE.
"""

from __future__ import annotations

from typing import Any

from .. import clock
from ..adapters.base import AdapterSession
from ..adapters.registry import AdapterRegistry
from ..audit.log import AuditLogger
from ..db.repositories import AccountRepository, ConnectionRepository
from ..domain.enums import (
    AuthType,
    ConnectionProviderKind,
    ConsentScope,
    DecisionOutcome,
    HealthStatus,
    LifecycleState,
    Platform,
)
from ..domain.ids import account_id as mint_account_id
from ..domain.models import Account, Authorization, Persona
from ..errors import InvalidState, LockHeld, NotFound
from ..vault.provider import ConnectionProvider


class AccountService:
    def __init__(
        self,
        accounts: AccountRepository,
        connections: ConnectionRepository,
        registry: AdapterRegistry,
        provider: ConnectionProvider,
        audit: AuditLogger,
    ) -> None:
        self._accounts = accounts
        self._connections = connections
        self._registry = registry
        self._provider = provider
        self._audit = audit

    def _get(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise NotFound(f"account '{account_id}' not found")
        return account

    @staticmethod
    def _recompute_status(account: Account) -> None:
        if account.status in (LifecycleState.SUSPENDED, LifecycleState.RETIRED):
            return
        if account.connection_id and account.authorization.is_effective():
            account.status = LifecycleState.ACTIVE
        elif account.connection_id:
            account.status = LifecycleState.CONNECTED
        else:
            account.status = LifecycleState.DRAFT

    # ---- register ------------------------------------------------------------
    def register(
        self,
        caller: str,
        platform: str,
        handle: str,
        *,
        display_name: str | None = None,
        persona: dict[str, Any] | None = None,
        pool: str | None = None,
        tags: list[str] | None = None,
    ) -> Account:
        plat = Platform(platform)
        account = Account(
            account_id=mint_account_id(plat, handle),
            platform=plat,
            handle=handle,
            display_name=display_name,
            persona=Persona(**(persona or {})),
            pool=pool,
            tags=tags or [],
            status=LifecycleState.DRAFT,
        )
        self._accounts.add(account)
        self._audit.record(
            caller,
            "account_register",
            DecisionOutcome.ALLOW,
            account_id=account.account_id,
            message=f"registered {plat.value}:{handle}",
        )
        return account

    # ---- authorize -----------------------------------------------------------
    def authorize(
        self,
        caller: str,
        account_id: str,
        owner: str,
        consent_scope: list[str],
        *,
        evidence_ref: str | None = None,
        attested_by: str | None = None,
    ) -> Account:
        account = self._get(account_id)
        expected = account.record_version
        account.authorization = Authorization(
            authorized=True,
            owner=owner,
            consent_scope=[ConsentScope(s) for s in consent_scope],
            evidence_ref=evidence_ref,
            attested_by=attested_by or caller,
            attested_at=clock.now(),
        )
        self._recompute_status(account)
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_authorize",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=f"authorized by {attested_by or caller} for {owner}",
        )
        return account

    def revoke_authorization(self, caller: str, account_id: str, reason: str | None = None) -> Account:
        account = self._get(account_id)
        expected = account.record_version
        account.authorization.revoked_at = clock.now()
        account.status = LifecycleState.SUSPENDED
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_revoke",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=reason or "authorization revoked",
        )
        return account

    # ---- connect (store credentials + self-identify) -------------------------
    async def connect(
        self,
        caller: str,
        account_id: str,
        auth_type: str,
        credentials: dict[str, Any],
        *,
        scopes: list[str] | None = None,
        provider: str | None = None,
    ) -> Account:
        account = self._get(account_id)
        expected = account.record_version

        connection = self._provider.store_credentials(
            account_id=account.account_id,
            platform=account.platform,
            auth_type=AuthType(auth_type),
            payload=credentials,
            scopes=scopes,
        )
        if provider:
            connection.provider = ConnectionProviderKind(provider)
        self._connections.add(connection)
        account.connection_id = connection.connection_id

        adapter = self._registry.get(account.platform)
        session = AdapterSession(account=account, credentials=credentials)
        auth = await adapter.authenticate(session)
        if auth.platform_user_id:
            account.platform_user_id = auth.platform_user_id
        if auth.display_name and not account.display_name:
            account.display_name = auth.display_name

        # Self-identification (bot flag / self-label) where the platform requires it.
        compliance = await adapter.ensure_self_identification(session)
        account.compliance.bot_flag_set = compliance.bot_flag_set
        account.compliance.self_label = compliance.self_label
        account.capabilities = adapter.capabilities()

        self._recompute_status(account)
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_connect",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=f"connected ({auth_type}); status={account.status.value}",
        )
        return account

    def _session_with_creds(self, account: Account) -> AdapterSession:
        session = AdapterSession(account=account, credentials={})
        if account.connection_id:
            conn = self._connections.get(account.connection_id)
            if conn is not None:
                try:
                    session.credentials = self._provider.load_credentials(conn)
                except Exception:
                    session.credentials = {}
        return session

    # ---- refresh credentials -------------------------------------------------
    async def refresh_credentials(self, caller: str, account_id: str) -> Account:
        account = self._get(account_id)
        expected = account.record_version
        adapter = self._registry.get(account.platform)
        session = self._session_with_creds(account)
        result = await adapter.refresh_credentials(session)
        if result.new_credentials and account.connection_id:
            conn = self._connections.get(account.connection_id)
            if conn is not None:
                # Re-store rotated material under the same secret_ref (builtin vault path).
                from ..vault.provider import BuiltinConnectionProvider

                if isinstance(self._provider, BuiltinConnectionProvider):
                    self._provider._vault.store(result.new_credentials, secret_ref=conn.secret_ref)
        account.health.status = HealthStatus.OK if result.auth.ok else HealthStatus.REAUTH_NEEDED
        account.health.last_health_at = clock.now()
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_refresh_credentials",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=f"refresh ok={result.auth.ok}",
        )
        return account

    # ---- health check --------------------------------------------------------
    async def health_check(self, caller: str, account_id: str) -> Account:
        account = self._get(account_id)
        expected = account.record_version
        adapter = self._registry.get(account.platform)
        session = self._session_with_creds(account)
        report = await adapter.health_check(session)
        account.health.status = report.status
        account.health.last_health_at = clock.now()
        account.health.last_error = report.error
        account.health.detail = report.detail
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_health_check",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=f"health={report.status.value}",
        )
        return account

    # ---- patch (requires lock) -----------------------------------------------
    def patch(
        self,
        caller: str,
        account_id: str,
        lock_token: str,
        expected_version: int,
        updates: dict[str, Any],
    ) -> Account:
        account = self._get(account_id)
        lock = account.lock
        if lock is None or not lock.held_by(caller, lock_token):
            raise LockHeld("patch requires holding the account's checkout lock")
        if account.record_version != expected_version:
            from ..errors import Conflict

            raise Conflict(f"expected version {expected_version}, have {account.record_version}")

        allowed = {"persona", "tags", "pool", "policy_overrides", "requires_approval", "status"}
        for key, value in updates.items():
            if key not in allowed:
                raise InvalidState(f"field '{key}' is not patchable")
            if key == "persona":
                account.persona = Persona(**value)
            elif key == "status":
                account.status = LifecycleState(value)
            else:
                setattr(account, key, value)

        account = self._accounts.update(account, expected_version=expected_version)
        self._audit.record(
            caller,
            "account_patch",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=f"patched {sorted(updates.keys())}",
        )
        return account

    # ---- retire --------------------------------------------------------------
    def retire(self, caller: str, account_id: str, reason: str | None = None) -> Account:
        account = self._get(account_id)
        expected = account.record_version
        account.status = LifecycleState.RETIRED
        account = self._accounts.update(account, expected_version=expected)
        self._audit.record(
            caller,
            "account_retire",
            DecisionOutcome.ALLOW,
            account_id=account_id,
            message=reason or "retired",
        )
        return account

    # ---- reads ---------------------------------------------------------------
    def get(self, account_id: str) -> Account:
        return self._get(account_id)

    def list(
        self,
        platform: str | None = None,
        status: str | None = None,
        pool: str | None = None,
        tag: str | None = None,
    ) -> list[Account]:
        return self._accounts.list(
            platform=Platform(platform) if platform else None,
            status=status,
            pool=pool,
            tag=tag,
        )
