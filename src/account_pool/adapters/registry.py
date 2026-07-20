"""Adapter registry: resolve a :class:`PlatformAdapter` for a platform.

Adapters are cached per platform (one stateless-per-account instance each). For M0 every platform
resolves to a :class:`FakeAdapter`; real adapters register here as later milestones land.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial

from ..domain.enums import Platform
from .base import PlatformAdapter
from .fake import FakeAdapter

AdapterFactory = Callable[[], PlatformAdapter]


def _real_adapter_factories() -> dict[Platform, AdapterFactory]:
    """Real, network-backed adapters, imported lazily so their optional deps aren't required
    unless a platform is actually enabled."""
    from .reddit import RedditAdapter

    return {Platform.REDDIT: RedditAdapter}


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[Platform, AdapterFactory] = {}
        self._cache: dict[Platform, PlatformAdapter] = {}

    def register(self, platform: Platform, factory: AdapterFactory) -> None:
        self._factories[platform] = factory
        self._cache.pop(platform, None)

    def get(self, platform: Platform) -> PlatformAdapter:
        if platform not in self._cache:
            if platform not in self._factories:
                raise KeyError(f"no adapter registered for platform '{platform.value}'")
            self._cache[platform] = self._factories[platform]()
        return self._cache[platform]

    def platforms(self) -> list[Platform]:
        return list(self._factories.keys())


def default_registry() -> AdapterRegistry:
    """A registry with a FakeAdapter for every known platform (M0 default)."""
    registry = AdapterRegistry()
    for platform in Platform:
        registry.register(platform, partial(FakeAdapter, platform=platform))
    return registry


def build_registry(real_adapters: Iterable[str] | None = None) -> AdapterRegistry:
    """A registry that uses real adapters for the named platforms and FakeAdapter for the rest.

    ``real_adapters`` is an iterable of platform values (e.g. ``["reddit"]``). Global/​per-call
    ``dry_run`` still gates whether a real adapter actually writes.
    """
    registry = default_registry()
    wanted = {s.strip().lower() for s in (real_adapters or []) if s and s.strip()}
    if wanted:
        for platform, factory in _real_adapter_factories().items():
            if platform.value in wanted:
                registry.register(platform, factory)
    return registry
