"""Identifier and token generation helpers."""

from __future__ import annotations

import re
import secrets
import uuid

from .enums import Platform

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "acct"


def account_id(platform: Platform, handle: str) -> str:
    """Mint a stable-ish, human-readable account id: ``acct_<platform>_<handle-slug>_<rand>``."""
    return f"acct_{platform.value}_{_slug(handle)}_{secrets.token_hex(3)}"


def new_id(prefix: str) -> str:
    """Mint an opaque id with the given prefix, e.g. ``act_<uuid4hex>``."""
    return f"{prefix}_{uuid.uuid4().hex}"


def lock_token() -> str:
    """A random, unguessable lock token."""
    return secrets.token_urlsafe(24)


def secret_ref() -> str:
    """Opaque pointer used to look ciphertext up in the vault (never the secret itself)."""
    return f"vault_{uuid.uuid4().hex}"
