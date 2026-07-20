"""The acting orchestrator: ``draft -> validate -> (approval) -> execute -> audit``.

This is where the guard result is turned into one of three outcomes — refused, queued-for-approval,
or executed — and where every path emits exactly one audit event. Trackers (rate, coordination,
self-promo) are updated only on a successful execute.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .. import clock
from ..adapters.base import (
    ActionResult,
    AdapterSession,
    ContentInvalid,
    ReadResult,
    SearchResult,
    UnsupportedCapability,
)
from ..adapters.registry import AdapterRegistry
from ..approvals.queue import ApprovalQueue
from ..audit.log import AuditLogger, trace_snapshot
from ..config import Settings, get_settings
from ..db.repositories import (
    AccountRepository,
    ActionRepository,
    ConnectionRepository,
    DraftRepository,
)
from ..domain.enums import (
    ACTION_CONSENT,
    ActionState,
    ActionType,
    DecisionOutcome,
    DenialCode,
    PublishMode,
    ReviewState,
)
from ..domain.ids import new_id
from ..domain.models import (
    Account,
    Action,
    ApprovalItem,
    ContentDraft,
    DecisionStep,
    TargetRef,
)
from ..errors import InvalidState, NotFound
from ..policy.context import GuardContext
from ..policy.decisions import Decision
from ..policy.engine import PolicyEngine
from ..policy.policies import resolve_policy
from ..policy.ratelimit import RateLimiter
from ..policy.trackers import CoordinationTracker, SelfPromoLedger, is_promotional
from ..vault.provider import ConnectionProvider


class ActionService:
    def __init__(
        self,
        accounts: AccountRepository,
        connections: ConnectionRepository,
        drafts: DraftRepository,
        actions: ActionRepository,
        approvals: ApprovalQueue,
        audit: AuditLogger,
        registry: AdapterRegistry,
        provider: ConnectionProvider,
        engine: PolicyEngine,
        rate_limiter: RateLimiter,
        coordination: CoordinationTracker,
        promo_ledger: SelfPromoLedger,
        settings: Settings | None = None,
        notifier: Callable[[ApprovalItem, Account], None] | None = None,
    ) -> None:
        self._accounts = accounts
        self._connections = connections
        self._drafts = drafts
        self._actions = actions
        self._approvals = approvals
        self._audit = audit
        self._registry = registry
        self._provider = provider
        self._engine = engine
        self._rate = rate_limiter
        self._coord = coordination
        self._promo = promo_ledger
        self._settings = settings or get_settings()
        self._notifier = notifier

    # ---- lookups -------------------------------------------------------------
    def _get_account(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise NotFound(f"account '{account_id}' not found")
        return account

    def _get_draft(self, draft_id: str) -> ContentDraft:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise NotFound(f"draft '{draft_id}' not found")
        return draft

    def _load_session(self, account: Account) -> AdapterSession:
        creds: dict[str, Any] = {}
        if account.connection_id:
            conn = self._connections.get(account.connection_id)
            if conn is not None:
                try:
                    creds = self._provider.load_credentials(conn)
                except Exception:  # missing/rotated secret — adapters must handle empty creds
                    creds = {}
        return AdapterSession(account=account, credentials=creds)

    def _build_ctx(
        self,
        account: Account,
        action_type: ActionType,
        caller: str,
        *,
        lock_token: str | None = None,
        draft: ContentDraft | None = None,
        target: TargetRef | None = None,
        react_kind: str | None = None,
    ) -> GuardContext:
        adapter = self._registry.get(account.platform)
        return GuardContext(
            account=account,
            action_type=action_type,
            capabilities=adapter.capabilities(),
            policy=resolve_policy(account),
            caller=caller,
            rate_limiter=self._rate,
            coordination=self._coord,
            promo_ledger=self._promo,
            lock_token=lock_token,
            draft=draft,
            target=target,
            react_kind=react_kind,
        )

    @staticmethod
    def _to_steps(trace: list[Decision]) -> list[DecisionStep]:
        return [
            DecisionStep(
                guard=d.guard,
                outcome=d.outcome,
                denial_code=d.denial_code,
                message=d.message,
            )
            for d in trace
        ]

    # ---- drafts --------------------------------------------------------------
    def create_draft(
        self,
        account_id: str,
        body: str,
        title: str | None = None,
        media_refs: list[str] | None = None,
        disclosure: str | None = None,
    ) -> ContentDraft:
        self._get_account(account_id)  # validate existence
        draft = ContentDraft(
            draft_id=new_id("draft"),
            account_id=account_id,
            body=body,
            title=title,
            media_refs=media_refs or [],
            disclosure=disclosure,
        )
        return self._drafts.upsert(draft)

    def update_draft(
        self,
        draft_id: str,
        body: str | None = None,
        title: str | None = None,
        media_refs: list[str] | None = None,
        disclosure: str | None = None,
    ) -> ContentDraft:
        draft = self._get_draft(draft_id)
        if body is not None:
            draft.body = body
        if title is not None:
            draft.title = title
        if media_refs is not None:
            draft.media_refs = media_refs
        if disclosure is not None:
            draft.disclosure = disclosure
        draft.revision += 1
        draft.updated_at = clock.now()
        return self._drafts.upsert(draft)

    # ---- validate (dry policy check, no execution, no audit) -----------------
    async def validate(
        self,
        caller: str,
        account_id: str,
        action_type: str,
        *,
        draft_id: str | None = None,
        target_raw: str | None = None,
        react_kind: str | None = None,
        lock_token: str | None = None,
    ) -> dict[str, Any]:
        account = self._get_account(account_id)
        atype = ActionType(action_type)
        draft = self._get_draft(draft_id) if draft_id else None
        target = await self._resolve(account, target_raw) if target_raw else None
        ctx = self._build_ctx(
            account,
            atype,
            caller,
            lock_token=lock_token,
            draft=draft,
            target=target,
            react_kind=react_kind,
        )
        result = self._engine.evaluate(ctx)
        return {
            "outcome": result.outcome.value,
            "denial_code": result.denial_code.value if result.denial_code else None,
            "message": result.decision.message,
            **trace_snapshot(result.trace),
        }

    # ---- write verbs ---------------------------------------------------------
    async def _resolve(self, account: Account, target_raw: str) -> TargetRef:
        adapter = self._registry.get(account.platform)
        session = self._load_session(account)
        return await adapter.resolve_target(session, target_raw)

    async def publish(
        self,
        caller: str,
        account_id: str,
        lock_token: str,
        draft_id: str,
        *,
        idempotency_key: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> Action:
        account = self._get_account(account_id)
        draft = self._get_draft(draft_id)
        return await self._submit_write(
            caller,
            account,
            ActionType.PUBLISH,
            lock_token,
            draft=draft,
            idempotency_key=idempotency_key,
            scheduled_for=scheduled_for,
        )

    async def comment(
        self,
        caller: str,
        account_id: str,
        lock_token: str,
        target_raw: str,
        draft_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> Action:
        account = self._get_account(account_id)
        draft = self._get_draft(draft_id)
        target = await self._resolve(account, target_raw)
        return await self._submit_write(
            caller,
            account,
            ActionType.COMMENT,
            lock_token,
            draft=draft,
            target=target,
            idempotency_key=idempotency_key,
        )

    async def react(
        self,
        caller: str,
        account_id: str,
        lock_token: str,
        target_raw: str,
        kind: str,
        *,
        idempotency_key: str | None = None,
    ) -> Action:
        account = self._get_account(account_id)
        target = await self._resolve(account, target_raw)
        return await self._submit_write(
            caller,
            account,
            ActionType.REACT,
            lock_token,
            target=target,
            react_kind=kind,
            idempotency_key=idempotency_key,
        )

    async def _submit_write(
        self,
        caller: str,
        account: Account,
        action_type: ActionType,
        lock_token: str,
        *,
        draft: ContentDraft | None = None,
        target: TargetRef | None = None,
        react_kind: str | None = None,
        idempotency_key: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> Action:
        if idempotency_key:
            existing = self._actions.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        action = Action(
            action_id=new_id("act"),
            account_id=account.account_id,
            type=action_type,
            target=target,
            react_kind=react_kind,
            draft_id=draft.draft_id if draft else None,
            requested_by=caller,
            idempotency_key=idempotency_key,
            scheduled_for=scheduled_for,
        )
        ctx = self._build_ctx(
            account,
            action_type,
            caller,
            lock_token=lock_token,
            draft=draft,
            target=target,
            react_kind=react_kind,
        )
        result = self._engine.evaluate(ctx)
        action.decision_trace = self._to_steps(result.trace)
        snapshot = trace_snapshot(result.trace)

        if result.outcome == DecisionOutcome.DENY:
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                caller,
                action_type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=result.denial_code,
                policy_snapshot=snapshot,
                message=result.decision.message,
            )
            return action

        if result.outcome == DecisionOutcome.ROUTE_TO_APPROVAL:
            action.state = ActionState.NEEDS_APPROVAL
            summary = f"{action_type.value} on {target.raw if target else 'own channel'}"
            approval = self._approvals.submit(
                action, summary=summary, pinned_revision=draft.revision if draft else None
            )
            action.result = {"approval_id": approval.approval_id, "state": "needs_approval"}
            self._actions.upsert(action)
            self._audit.record(
                caller,
                action_type.value,
                DecisionOutcome.ROUTE_TO_APPROVAL,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=DenialCode.APPROVAL_REQUIRED,
                policy_snapshot=snapshot,
                message=f"queued approval {approval.approval_id}",
            )
            self._notify(approval, account)
            return action

        return await self._execute(
            action,
            account,
            draft=draft,
            target=target,
            react_kind=react_kind,
            actor=caller,
            policy_snapshot=snapshot,
        )

    async def _execute(
        self,
        action: Action,
        account: Account,
        *,
        draft: ContentDraft | None,
        target: TargetRef | None,
        react_kind: str | None,
        actor: str,
        policy_snapshot: dict[str, Any] | None = None,
    ) -> Action:
        action.state = ActionState.EXECUTING
        self._actions.upsert(action)

        adapter = self._registry.get(account.platform)
        session = self._load_session(account)
        policy = resolve_policy(account)
        dry = self._settings.dry_run
        verb = action.type.value

        try:
            res = await self._dispatch(adapter, session, action.type, draft, target, react_kind, policy, dry)
        except (UnsupportedCapability, ContentInvalid) as exc:
            code = (
                DenialCode.CONTENT_INVALID
                if isinstance(exc, ContentInvalid)
                else DenialCode.CAPABILITY_UNSUPPORTED
            )
            action.state = ActionState.FAILED
            action.result = {"error": str(exc), "denial_code": code.value}
            self._actions.upsert(action)
            self._audit.record(
                actor,
                verb,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=code,
                message=str(exc),
                policy_snapshot=policy_snapshot,
            )
            return action

        # An adapter that returned a non-ok result (e.g. a platform-side rejection) fails the action.
        if not res.ok:
            action.state = ActionState.FAILED
            action.result = res.model_dump()
            self._actions.upsert(action)
            self._audit.record(
                actor,
                verb,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                platform_result=res.model_dump(),
                policy_snapshot=policy_snapshot,
                message="adapter reported failure",
            )
            return action

        # Success: update trackers.
        self._rate.consume(account.account_id, verb)
        if target is not None and action.type in (ActionType.COMMENT, ActionType.REACT):
            self._coord.record(f"{account.platform.value}:{target.raw}", account.account_id)
        if draft is not None and action.type in (ActionType.PUBLISH, ActionType.COMMENT):
            self._promo.record(account.account_id, is_promotional(draft, account))

        action.result = res.model_dump()
        action.state = ActionState.DONE
        self._actions.upsert(action)
        self._audit.record(
            actor,
            verb,
            DecisionOutcome.ALLOW,
            account_id=account.account_id,
            action_id=action.action_id,
            platform_result=res.model_dump(),
            policy_snapshot=policy_snapshot,
            message="executed (dry-run)" if dry else "executed",
        )
        return action

    async def _dispatch(
        self, adapter, session, action_type, draft, target, react_kind, policy, dry
    ) -> ActionResult:
        if action_type == ActionType.PUBLISH:
            if policy.publish_mode in (PublishMode.DRAFT_ONLY, PublishMode.MANUAL):
                # Draft-only (Medium) / manual (Substack): stage the content for a human/draft
                # workflow. No automated network write is made for these modes.
                return ActionResult(
                    ok=True,
                    dry_run=dry,
                    detail={
                        "staged": True,
                        "manual": policy.publish_mode == PublishMode.MANUAL,
                        "publish_mode": policy.publish_mode.value,
                        "draft_id": draft.draft_id if draft else None,
                        "title": draft.title if draft else None,
                    },
                )
            return await adapter.publish(session, draft, dry_run=dry)
        if action_type == ActionType.COMMENT:
            return await adapter.comment(session, target, draft, dry_run=dry)
        if action_type == ActionType.REACT:
            return await adapter.react(session, target, react_kind or "like", dry_run=dry)
        raise UnsupportedCapability(f"cannot execute verb '{action_type.value}'")

    # ---- read verbs ----------------------------------------------------------
    async def read(self, caller: str, account_id: str, target_raw: str) -> Action:
        account = self._get_account(account_id)
        target = await self._resolve(account, target_raw)
        return await self._run_read(caller, account, ActionType.READ, target=target)

    async def search(self, caller: str, account_id: str, query: str, *, limit: int = 25) -> Action:
        account = self._get_account(account_id)
        return await self._run_read(caller, account, ActionType.SEARCH, query=query, limit=limit)

    async def _run_read(
        self,
        caller: str,
        account: Account,
        action_type: ActionType,
        *,
        target: TargetRef | None = None,
        query: str | None = None,
        limit: int = 25,
    ) -> Action:
        action = Action(
            action_id=new_id("act"),
            account_id=account.account_id,
            type=action_type,
            target=target,
            requested_by=caller,
        )
        ctx = self._build_ctx(account, action_type, caller, target=target)
        result = self._engine.evaluate(ctx)
        action.decision_trace = self._to_steps(result.trace)
        snapshot = trace_snapshot(result.trace)

        if result.outcome == DecisionOutcome.DENY:
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                caller,
                action_type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=result.denial_code,
                policy_snapshot=snapshot,
                message=result.decision.message,
            )
            return action

        action.state = ActionState.EXECUTING
        adapter = self._registry.get(account.platform)
        session = self._load_session(account)
        res: ReadResult | SearchResult
        if action_type == ActionType.SEARCH:
            res = await adapter.search(session, query or "", limit=limit)
        else:
            assert target is not None
            res = await adapter.read(session, target)
        self._rate.consume(account.account_id, action_type.value)
        action.result = res.model_dump()
        action.state = ActionState.DONE
        self._actions.upsert(action)
        self._audit.record(
            caller,
            action_type.value,
            DecisionOutcome.ALLOW,
            account_id=account.account_id,
            action_id=action.action_id,
            platform_result=res.model_dump(),
            policy_snapshot=snapshot,
            message="read",
        )
        return action

    # ---- approvals -----------------------------------------------------------
    async def decide_approval(
        self, approval_id: str, decision: str, decided_by: str, reason: str | None = None
    ) -> dict[str, Any]:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise NotFound(f"approval '{approval_id}' not found")
        action = self._actions.get(approval.action_id)
        if action is None:
            raise NotFound(f"action '{approval.action_id}' not found")
        account = self._get_account(action.account_id)

        if decision == "request_changes":
            self._approvals.set_state(
                approval, ReviewState.CHANGES_REQUESTED, decided_by=decided_by, reason=reason
            )
            return {"approval_id": approval_id, "review_state": ReviewState.CHANGES_REQUESTED.value}

        if decision == "reject":
            self._approvals.set_state(
                approval,
                ReviewState.CHANGES_REQUESTED,
                decided_by=decided_by,
                reason=reason or "rejected",
            )
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                decided_by,
                action.type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=DenialCode.APPROVAL_REQUIRED,
                message=reason or "rejected by reviewer",
            )
            return {"approval_id": approval_id, "action_state": ActionState.REFUSED.value}

        if decision != "approve":
            raise InvalidState(f"unknown decision '{decision}'")

        # An approval that has aged past its TTL can no longer be approved.
        if approval.is_expired():
            self._approvals.set_state(
                approval,
                ReviewState.CHANGES_REQUESTED,
                decided_by=decided_by,
                reason="approval expired",
            )
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                decided_by,
                action.type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=DenialCode.APPROVAL_STALE,
                message="approval expired",
            )
            return {
                "approval_id": approval_id,
                "action_state": ActionState.REFUSED.value,
                "denial_code": DenialCode.APPROVAL_STALE.value,
            }

        # ---- approve: re-check staleness + eligibility, then execute ----
        draft = self._get_draft(action.draft_id) if action.draft_id else None
        if (
            draft is not None
            and approval.pinned_revision is not None
            and draft.revision != approval.pinned_revision
        ):
            self._approvals.set_state(
                approval,
                ReviewState.CHANGES_REQUESTED,
                decided_by=decided_by,
                reason="draft changed after approval",
            )
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                decided_by,
                action.type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=DenialCode.APPROVAL_STALE,
                message="draft revision changed",
            )
            return {
                "approval_id": approval_id,
                "action_state": ActionState.REFUSED.value,
                "denial_code": DenialCode.APPROVAL_STALE.value,
            }

        scope = ACTION_CONSENT[action.type]
        if not account.is_active() or not account.authorization.permits(scope):
            self._approvals.set_state(
                approval,
                ReviewState.CHANGES_REQUESTED,
                decided_by=decided_by,
                reason="account no longer eligible",
            )
            action.state = ActionState.REFUSED
            self._actions.upsert(action)
            self._audit.record(
                decided_by,
                action.type.value,
                DecisionOutcome.DENY,
                account_id=account.account_id,
                action_id=action.action_id,
                denial_code=DenialCode.NOT_AUTHORIZED,
                message="account no longer eligible",
            )
            return {
                "approval_id": approval_id,
                "action_state": ActionState.REFUSED.value,
                "denial_code": DenialCode.NOT_AUTHORIZED.value,
            }

        self._approvals.set_state(approval, ReviewState.APPROVED, decided_by=decided_by, reason=reason)
        executed = await self._execute(
            action,
            account,
            draft=draft,
            target=action.target,
            react_kind=action.react_kind,
            actor=decided_by,
        )
        return {
            "approval_id": approval_id,
            "review_state": ReviewState.APPROVED.value,
            "action_id": executed.action_id,
            "action_state": executed.state.value,
            "result": executed.result,
        }

    async def resubmit_approval(self, caller: str, approval_id: str) -> dict[str, Any]:
        """Re-open a changes-requested approval against the latest draft revision for re-review."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise NotFound(f"approval '{approval_id}' not found")
        action = self._actions.get(approval.action_id)
        if action is None:
            raise NotFound(f"action '{approval.action_id}' not found")
        account = self._get_account(action.account_id)
        draft = self._get_draft(action.draft_id) if action.draft_id else None
        self._approvals.reopen(approval, pinned_revision=draft.revision if draft else None)
        action.state = ActionState.NEEDS_APPROVAL
        self._actions.upsert(action)
        self._audit.record(
            caller,
            action.type.value,
            DecisionOutcome.ROUTE_TO_APPROVAL,
            account_id=account.account_id,
            action_id=action.action_id,
            denial_code=DenialCode.APPROVAL_REQUIRED,
            message="resubmitted for review",
        )
        self._notify(approval, account)
        return {
            "approval_id": approval_id,
            "review_state": ReviewState.OPEN.value,
            "pinned_revision": approval.pinned_revision,
        }

    def _notify(self, approval: ApprovalItem, account: Account) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier(approval, account)
        except Exception:  # a failing notifier must never break the acting path
            pass

    # ---- reads for observability ---------------------------------------------
    def get_action(self, action_id: str) -> Action | None:
        return self._actions.get(action_id)

    def list_open_approvals(
        self, platform: str | None = None, account_id: str | None = None
    ) -> list[ApprovalItem]:
        return self._approvals.list_open(platform=platform, account_id=account_id)

    def get_approval(self, approval_id: str) -> ApprovalItem | None:
        return self._approvals.get(approval_id)
