"""Connection providers abstract *where* credentials live, so the builtin vault can later be
swapped for Nango/Composio without touching adapters or the guard.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..domain.enums import AuthType, ConnectionProviderKind, Platform
from ..domain.ids import new_id
from ..domain.models import Connection
from .vault import EncryptedVault


@runtime_checkable
class ConnectionProvider(Protocol):
    """Stores/loads the secret material behind a :class:`Connection`."""

    kind: ConnectionProviderKind

    def store_credentials(
        self,
        account_id: str,
        platform: Platform,
        auth_type: AuthType,
        payload: dict[str, Any],
        scopes: list[str] | None = ...,
    ) -> Connection: ...

    def load_credentials(self, connection: Connection) -> dict[str, Any]: ...

    def delete(self, connection: Connection) -> None: ...


class BuiltinConnectionProvider:
    """Default provider: secret material lives in the local :class:`EncryptedVault`."""

    kind = ConnectionProviderKind.BUILTIN

    def __init__(self, vault: EncryptedVault) -> None:
        self._vault = vault

    def store_credentials(
        self,
        account_id: str,
        platform: Platform,
        auth_type: AuthType,
        payload: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> Connection:
        secret_ref = self._vault.store(payload)
        return Connection(
            connection_id=new_id("conn"),
            account_id=account_id,
            platform=platform,
            auth_type=auth_type,
            provider=self.kind,
            scopes=list(scopes or []),
            secret_ref=secret_ref,
        )

    def load_credentials(self, connection: Connection) -> dict[str, Any]:
        return self._vault.retrieve(connection.secret_ref)

    def delete(self, connection: Connection) -> None:
        self._vault.delete(connection.secret_ref)
