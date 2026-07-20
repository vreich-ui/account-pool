"""Caller identity helpers.

An external agent self-declares its ``agent_name`` on tools that lock or act — this is *coordination,
not security* (it names the lock holder and the audit actor). Real per-agent authentication is a
later milestone; over HTTP the whole server sits behind a bearer token.
"""

from __future__ import annotations

_DEFAULT_AGENT = "anonymous-agent"


def normalize_agent(agent_name: str | None) -> str:
    name = (agent_name or "").strip()
    return name or _DEFAULT_AGENT
