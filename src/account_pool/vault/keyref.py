"""Resolve the vault master key.

Precedence:
1. The env var *named* by ``settings.vault_master_key_env`` (its value is the Fernet key).
2. Dev only: a local key file (generated on first use), gated by ``vault_allow_dev_keyfile``.
3. Otherwise raise — production must supply the key via the environment / a secrets manager.

The key material is never written to the metadata DB or logged.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import Settings, get_settings


def generate_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key (32 bytes)."""
    return Fernet.generate_key().decode("ascii")


def _validate(key: str) -> bytes:
    raw = key.strip().encode("ascii")
    # Constructing a Fernet validates the key format; raises ValueError otherwise.
    Fernet(raw)
    return raw


def resolve_master_key(settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()

    env_value = os.environ.get(settings.vault_master_key_env)
    if env_value:
        return _validate(env_value)

    if settings.vault_allow_dev_keyfile and not settings.is_prod:
        path = Path(settings.vault_dev_keyfile)
        if path.exists():
            return _validate(path.read_text(encoding="ascii"))
        key = generate_key()
        path.write_text(key, encoding="ascii")
        # Best-effort tighten permissions (0600).
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return _validate(key)

    raise RuntimeError(
        f"No vault master key: set env var '{settings.vault_master_key_env}' "
        "(generate one with `python -m account_pool.vault.keyref --generate`)."
    )


def _main() -> int:
    if "--generate" in sys.argv:
        print(generate_key())
        return 0
    print("usage: python -m account_pool.vault.keyref --generate", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
