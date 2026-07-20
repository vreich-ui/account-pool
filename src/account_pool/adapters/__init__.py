"""Platform adapters: one common interface, one implementation per platform.

The abstraction deliberately has **no** ``scrape`` method and no evasion surface. Draft-only/manual
platforms raise on any real network write, so a mode mismatch fails closed.
"""

from .base import (
    ActionResult,
    AdapterSession,
    AuthState,
    ComplianceState,
    ContentInvalid,
    HealthReport,
    PlatformAdapter,
    ReadResult,
    RefreshResult,
    SearchResult,
    UnsupportedCapability,
)
from .fake import FakeAdapter
from .registry import AdapterRegistry, build_registry, default_registry

__all__ = [
    "PlatformAdapter",
    "AdapterSession",
    "AuthState",
    "RefreshResult",
    "HealthReport",
    "ComplianceState",
    "ActionResult",
    "ReadResult",
    "SearchResult",
    "UnsupportedCapability",
    "ContentInvalid",
    "FakeAdapter",
    "AdapterRegistry",
    "default_registry",
    "build_registry",
]
