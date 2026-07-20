"""The guard matrix: each compliance boundary has a test that proves it fires."""

from __future__ import annotations

from datetime import timedelta

from account_pool import clock
from account_pool.adapters.fake import FakeAdapter
from account_pool.domain.enums import (
    ActionType,
    ConsentScope,
    DenialCode,
    LifecycleState,
    Platform,
)
from account_pool.domain.models import (
    Account,
    Authorization,
    ContentDraft,
    LockLease,
    TargetRef,
)
from account_pool.policy.context import GuardContext
from account_pool.policy.engine import PolicyEngine
from account_pool.policy.policies import resolve_policy
from account_pool.policy.ratelimit import RateLimiter
from account_pool.policy.trackers import CoordinationTracker, SelfPromoLedger

_UNSET = object()
ENGINE = PolicyEngine()


def active_account(
    platform: Platform,
    *,
    bot_flag=_UNSET,
    self_label=_UNSET,
    authorized: bool = True,
    scopes=None,
    owned_domains=None,
    requires_approval: bool = True,
    status: LifecycleState = LifecycleState.ACTIVE,
    locked: bool = True,
    holder: str = "agent-1",
    token: str = "tok",
) -> Account:
    a = Account(
        account_id=f"acct_{platform.value}",
        platform=platform,
        handle="brand",
        status=status,
        requires_approval=requires_approval,
    )
    a.authorization = Authorization(
        authorized=authorized,
        owner="owner",
        consent_scope=list(scopes)
        if scopes is not None
        else [ConsentScope.PUBLISH, ConsentScope.COMMENT, ConsentScope.REACT, ConsentScope.READ],
    )
    caps = FakeAdapter(platform).capabilities()
    a.compliance.bot_flag_set = caps.requires_bot_flag if bot_flag is _UNSET else bot_flag
    a.compliance.self_label = (
        ("automated" if caps.self_label_supported else None) if self_label is _UNSET else self_label
    )
    if owned_domains:
        a.persona.owned_domains = owned_domains
    if locked:
        now = clock.now()
        a.lock = LockLease(
            holder=holder, token=token, acquired_at=now, expires_at=now + timedelta(minutes=10)
        )
    return a


def ctx(
    a: Account,
    atype: ActionType,
    *,
    rl=None,
    coord=None,
    promo=None,
    draft=None,
    target=None,
    react_kind=None,
    caller="agent-1",
    lock_token="tok",
) -> GuardContext:
    return GuardContext(
        account=a,
        action_type=atype,
        capabilities=FakeAdapter(a.platform).capabilities(),
        policy=resolve_policy(a),
        caller=caller,
        rate_limiter=rl or RateLimiter(),
        coordination=coord or CoordinationTracker(),
        promo_ledger=promo or SelfPromoLedger(),
        lock_token=lock_token,
        draft=draft,
        target=target,
        react_kind=react_kind,
    )


def draft_for(a: Account, body: str = "hello world") -> ContentDraft:
    return ContentDraft(draft_id="d1", account_id=a.account_id, body=body)


def third_party(raw="someone/post") -> TargetRef:
    return TargetRef(raw=raw, is_owned=False, resolved=True)


# ---- authorization / lifecycle ----
def test_unauthorized_denied():
    a = active_account(Platform.MASTODON, authorized=False)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_deny and r.denial_code == DenialCode.NOT_AUTHORIZED


def test_not_active_denied():
    a = active_account(Platform.MASTODON, status=LifecycleState.CONNECTED)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_deny and r.denial_code == DenialCode.ACCOUNT_NOT_ACTIVE


def test_missing_consent_scope_denied():
    a = active_account(Platform.MASTODON, scopes=[ConsentScope.READ])
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_deny and r.denial_code == DenialCode.NOT_AUTHORIZED


# ---- locking ----
def test_write_requires_lock():
    a = active_account(Platform.MASTODON, locked=False)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a), lock_token=None))
    assert r.is_deny and r.denial_code == DenialCode.LOCK_REQUIRED


def test_lock_held_by_other():
    a = active_account(Platform.MASTODON, holder="agent-1")
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a), caller="agent-2"))
    assert r.is_deny and r.denial_code == DenialCode.LOCK_HELD_BY_OTHER


# ---- self-identification ----
def test_mastodon_requires_bot_flag():
    a = active_account(Platform.MASTODON, bot_flag=False)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_deny and r.denial_code == DenialCode.BOT_IDENTIFICATION_REQUIRED


def test_bluesky_requires_self_label():
    a = active_account(Platform.BLUESKY, self_label=None)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_deny and r.denial_code == DenialCode.BOT_IDENTIFICATION_REQUIRED


# ---- manipulation ----
def test_vote_kind_hard_blocked():
    a = active_account(Platform.MASTODON)  # react allowed, but voting is not
    r = ENGINE.evaluate(ctx(a, ActionType.REACT, react_kind="upvote", target=third_party()))
    assert r.is_deny and r.denial_code == DenialCode.VOTE_MANIPULATION_BLOCKED


def test_reddit_offers_no_react():
    a = active_account(Platform.REDDIT)
    r = ENGINE.evaluate(ctx(a, ActionType.REACT, react_kind="like", target=third_party()))
    assert r.is_deny and r.denial_code == DenialCode.CAPABILITY_UNSUPPORTED


# ---- self-promotion ratio ----
def test_is_promotional_domain_matching():
    from account_pool.policy.trackers import is_promotional

    a = active_account(Platform.REDDIT, owned_domains=["brand.com"])
    assert is_promotional(draft_for(a, "see https://www.brand.com/x"), a)
    assert is_promotional(draft_for(a, "see https://blog.brand.com/x"), a)  # subdomain
    assert not is_promotional(draft_for(a, "see https://brandx.com/x"), a)  # not owned
    assert not is_promotional(draft_for(a, "no links here"), a)


def test_reddit_self_promo_ratio_blocks_early():
    a = active_account(Platform.REDDIT, owned_domains=["brand.com"])
    promo = SelfPromoLedger()  # no non-promo history yet
    d = draft_for(a, "check this out https://brand.com/launch")
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=d, promo=promo))
    assert r.is_deny and r.denial_code == DenialCode.SELF_PROMO_RATIO


def test_reddit_self_promo_allowed_after_enough_non_promo():
    a = active_account(Platform.REDDIT, owned_domains=["brand.com"])
    promo = SelfPromoLedger()
    for _ in range(9):
        promo.record(a.account_id, promotional=False)
    d = draft_for(a, "our post https://brand.com/launch")
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=d, promo=promo))
    assert r.is_allow


# ---- rate limiting ----
def test_rate_limit_blocks():
    a = active_account(Platform.REDDIT)
    rl = RateLimiter()
    rl.consume(a.account_id, "publish")  # reddit publish limit is 1/min
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a), rl=rl))
    assert r.is_deny and r.denial_code == DenialCode.RATE_LIMITED


# ---- coordination ----
def test_coordination_blocks_astroturf():
    a = active_account(Platform.MASTODON)
    coord = CoordinationTracker(max_distinct_accounts=2)
    key = "mastodon:someone/post"
    coord.record(key, "acct_a")
    coord.record(key, "acct_b")
    r = ENGINE.evaluate(ctx(a, ActionType.COMMENT, draft=draft_for(a), target=third_party(), coord=coord))
    assert r.is_deny and r.denial_code == DenialCode.COORDINATION_BLOCKED


# ---- autonomy ----
def test_publish_own_channel_auto():
    a = active_account(Platform.MASTODON)
    r = ENGINE.evaluate(ctx(a, ActionType.PUBLISH, draft=draft_for(a)))
    assert r.is_allow


def test_comment_third_party_routes_to_approval():
    a = active_account(Platform.MASTODON)
    r = ENGINE.evaluate(ctx(a, ActionType.COMMENT, draft=draft_for(a), target=third_party()))
    assert r.is_route and r.denial_code == DenialCode.APPROVAL_REQUIRED


def test_fully_autonomous_account_skips_approval():
    a = active_account(Platform.MASTODON, requires_approval=False)
    r = ENGINE.evaluate(ctx(a, ActionType.COMMENT, draft=draft_for(a), target=third_party()))
    assert r.is_allow


def test_read_needs_no_lock():
    a = active_account(Platform.REDDIT, locked=False)
    r = ENGINE.evaluate(ctx(a, ActionType.READ, target=third_party("r/python"), lock_token=None))
    assert r.is_allow
