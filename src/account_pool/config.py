"""Runtime configuration (pydantic-settings).

All values may be supplied via environment variables prefixed with ``ACCOUNT_POOL_`` or via a
``.env`` file. Secrets are never stored here directly — the vault master key is referenced by the
*name* of the env var that holds it (:attr:`Settings.vault_master_key_env`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings, loaded once and cached via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="ACCOUNT_POOL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Core ----
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    # Global safety switch. When true, no adapter performs a real network write.
    dry_run: bool = True

    # ---- Storage ----
    database_url: str = "sqlite:///./account_pool.db"
    # Vault lives in its own store, separate from the metadata DB, so ciphertext never
    # mingles with queryable records.
    vault_path: str = "./account_pool_vault.db"

    # ---- Vault master key ----
    # Name of the env var whose value is the Fernet master key. The key value itself is read
    # from that env var at runtime and is never persisted.
    vault_master_key_env: str = "ACCOUNT_POOL_MASTER_KEY"
    # Dev-only: allow generating an ephemeral key file when the env var is absent. Never in prod.
    vault_allow_dev_keyfile: bool = True
    vault_dev_keyfile: str = "./account_pool_master.key"

    # ---- Adapters ----
    # Comma-separated platform values to back with real (network) adapters instead of the
    # in-memory FakeAdapter, e.g. "reddit". Global dry_run still gates whether they write.
    real_adapters: str = ""

    # ---- Policy defaults ----
    default_lock_ttl_seconds: int = 900
    # Third-party comments/replies/reactions require human approval by default (hybrid autonomy).
    default_require_approval: bool = True
    # Open approvals older than this are considered stale and cannot be approved (default 24h).
    approval_ttl_seconds: int = 86400

    @property
    def real_adapters_list(self) -> list[str]:
        return [s.strip() for s in self.real_adapters.split(",") if s.strip()]

    # ---- MCP transport ----
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8848
    mcp_bearer_env: str = "ACCOUNT_POOL_MCP_BEARER"

    # ---- Admin REST surface ----
    admin_host: str = "127.0.0.1"
    admin_port: int = 8849
    # Name of the env var holding the admin bearer token. If unset, the surface is open only in
    # non-prod (dev convenience); in prod an unset token denies all requests.
    admin_bearer_env: str = "ACCOUNT_POOL_ADMIN_BEARER"

    server_name: str = Field(default="account-pool", description="MCP server display name")

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that mutate the environment)."""
    get_settings.cache_clear()
