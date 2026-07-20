"""The individual guards. Each returns a :class:`Decision`; the engine short-circuits on the first
DENY or ROUTE. Read verbs skip write-only guards (lock, self-id, manipulation, coordination,
autonomy)."""

from __future__ import annotations

from typing import Protocol

from ..domain.enums import ACTION_CONSENT, ActionType, DenialCode, PublishMode
from .context import GuardContext
from .decisions import Decision, allow, deny, route
from .platform_rules import evaluate_platform_rules
from .trackers import VOTE_KINDS


class Guard(Protocol):
    """A guard names itself and returns a verdict for one acting request."""

    name: str

    def evaluate(self, ctx: GuardContext) -> Decision: ...


class AccountActiveGuard:
    name = "account_active"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.account.is_active():
            return deny(
                self.name,
                DenialCode.ACCOUNT_NOT_ACTIVE,
                f"account is {ctx.account.status.value}, not active",
            )
        return allow(self.name)


class LockGuard:
    name = "lock"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write:
            return allow(self.name)
        lock = ctx.account.lock
        if lock is None or not lock.is_active():
            return deny(self.name, DenialCode.LOCK_REQUIRED, "account must be checked out first")
        if lock.holder != ctx.caller:
            return deny(
                self.name,
                DenialCode.LOCK_HELD_BY_OTHER,
                f"held by '{lock.holder}'",
            )
        if ctx.lock_token != lock.token:
            return deny(self.name, DenialCode.LOCK_REQUIRED, "missing or invalid lock token")
        return allow(self.name)


class AuthorizationGuard:
    name = "authorization"

    def evaluate(self, ctx: GuardContext) -> Decision:
        scope = ACTION_CONSENT[ctx.action_type]
        if not ctx.account.authorization.permits(scope):
            return deny(
                self.name,
                DenialCode.NOT_AUTHORIZED,
                f"no effective authorization for consent scope '{scope.value}'",
            )
        return allow(self.name)


class CapabilityGuard:
    name = "capability"

    def evaluate(self, ctx: GuardContext) -> Decision:
        caps, policy, at = ctx.capabilities, ctx.policy, ctx.action_type
        if at not in policy.allowed_verbs:
            return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, f"verb '{at.value}' not allowed")

        if at == ActionType.PUBLISH:
            if not caps.can_publish:
                return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, "publish unsupported")
            # DRAFT_ONLY and MANUAL are allowed: the actions service stages a draft/export instead
            # of making a live post (no automated network write occurs for those modes).
            return allow(self.name)

        if at == ActionType.COMMENT:
            if not caps.can_comment:
                return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, "comment unsupported")
            if policy.publish_mode != PublishMode.API:
                return deny(
                    self.name,
                    DenialCode.PUBLISH_MODE_MANUAL,
                    "commenting requires an API publish mode",
                )
            return allow(self.name)

        if at == ActionType.REACT:
            if not (caps.can_react and policy.react_allowed):
                return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, "react unsupported")
            return allow(self.name)

        if at in (ActionType.READ, ActionType.MONITOR):
            if not caps.can_read:
                return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, "read unsupported")
            return allow(self.name)

        if at == ActionType.SEARCH:
            if not caps.can_search:
                return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, "search unsupported")
            return allow(self.name)

        return deny(self.name, DenialCode.CAPABILITY_UNSUPPORTED, f"unknown verb '{at.value}'")


class SelfIdentificationGuard:
    name = "self_identification"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write:
            return allow(self.name)
        c = ctx.account.compliance
        if ctx.policy.requires_bot_flag and not c.bot_flag_set:
            return deny(
                self.name,
                DenialCode.BOT_IDENTIFICATION_REQUIRED,
                "platform requires the account to be flagged as a bot",
            )
        if ctx.policy.requires_self_label and not c.self_label:
            return deny(
                self.name,
                DenialCode.BOT_IDENTIFICATION_REQUIRED,
                "platform requires an automated self-label",
            )
        return allow(self.name)


class RateLimitGuard:
    name = "rate_limit"

    def evaluate(self, ctx: GuardContext) -> Decision:
        verb = ctx.action_type.value
        limit = ctx.policy.rate_per_minute.get(verb, 0)
        if not ctx.rate_limiter.check(ctx.account.account_id, verb, limit):
            return deny(
                self.name,
                DenialCode.RATE_LIMITED,
                f"rate limit for '{verb}' ({limit}/min) exhausted",
            )
        return allow(self.name)


class ManipulationGuard:
    name = "manipulation"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write:
            return allow(self.name)
        if (
            ctx.action_type == ActionType.REACT
            and (ctx.react_kind or "").lower() in VOTE_KINDS
            and not ctx.policy.vote_allowed
        ):
            return deny(
                self.name,
                DenialCode.VOTE_MANIPULATION_BLOCKED,
                "voting is hard-blocked to prevent manipulation",
            )
        return allow(self.name)


class PlatformRulesGuard:
    name = "platform_rules"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write:
            return allow(self.name)
        return evaluate_platform_rules(ctx)


class CoordinationGuard:
    name = "coordination"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write or ctx.is_owned_target:
            return allow(self.name)
        if ctx.coordination.would_coordinate(ctx.target_key, ctx.account.account_id):
            return deny(
                self.name,
                DenialCode.COORDINATION_BLOCKED,
                "multiple pool accounts targeting the same item within the window",
            )
        return allow(self.name)


class AutonomyGuard:
    name = "autonomy"

    def evaluate(self, ctx: GuardContext) -> Decision:
        if not ctx.is_write:
            return allow(self.name)
        if ctx.account.policy_overrides.get("approve_all_writes"):
            return route(self.name, "account requires approval for all writes")
        if ctx.is_owned_target:
            return allow(self.name)  # auto-publish to an owned channel
        if ctx.account.requires_approval:
            return route(self.name, "third-party act requires human approval")
        return allow(self.name)


DEFAULT_GUARDS: list[Guard] = [
    AccountActiveGuard(),
    LockGuard(),
    AuthorizationGuard(),
    CapabilityGuard(),
    SelfIdentificationGuard(),
    RateLimitGuard(),
    ManipulationGuard(),
    PlatformRulesGuard(),
    CoordinationGuard(),
    AutonomyGuard(),
]
