"""Common exceptions surfaced to the MCP/REST layer."""

from __future__ import annotations


class AccountPoolError(RuntimeError):
    """Base class for expected, caller-facing errors."""


class NotFound(AccountPoolError):
    pass


class LockHeld(AccountPoolError):
    """The account is checked out by another agent."""


class Conflict(AccountPoolError):
    """Optimistic-concurrency clash (stale record_version)."""


class InvalidState(AccountPoolError):
    """The requested transition is not valid from the current state."""
