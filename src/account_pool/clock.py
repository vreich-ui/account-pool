"""Single source of 'now' so time can be frozen/injected in tests."""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)
