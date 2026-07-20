# Account Pool

A **compliance-first** tool that holds social-media accounts as governed **objects** and lets an
**external AI-agent workspace** drive them — posting, reviewing/reading, and commenting across major
platforms. The agent workspace lives elsewhere; this repo is the *tool* the agents call, exposed as
an **MCP server**.

Each account is a first-class object that is *acted upon* (registered, authorized, checked out,
health-checked, retired) and that *acts* (drafts, publishes, comments, reads, reacts) — every act
flowing `draft → validate → (approval) → execute → audit` through a single policy guard.

## What it does / doesn't do

**It will:** manage only accounts you own or are authorized to manage (per-account consent
attestation gates all acting); use official platform APIs; enforce per-platform policy (rate limits,
Reddit self-promo ratio + subreddit rules); require bot self-identification where platforms mandate
it; keep an append-only audit of every action; and route third-party comments/replies through an
approval queue.

**It will not** (enforced by *absence of capability*, not just policy): generate or fabricate
accounts; provide any proxy/fingerprint/CAPTCHA/ban-evasion surface; scrape in violation of ToS;
manipulate votes or engagement (Reddit voting is hard-blocked); or coordinate accounts to fake
consensus. You cannot register an account you can't attest to owning.

## Status

**M0 — spine.** Domain model, encrypted vault, policy guard, audit, approvals, and the MCP surface,
all exercised end-to-end with an in-memory `FakeAdapter` and a global dry-run.

**M1 — Reddit.** A real `asyncpraw`-backed adapter (`adapters/reddit.py`): authenticate, read a
submission/comment, search, publish a self-post to the account's **own profile** (`u_<username>`),
and reply to a submission/comment (third-party replies route to approval). Voting is absent by design.

**M2 — Mastodon + Bluesky.** `adapters/mastodon.py` (Mastodon.py, sync SDK wrapped in a worker
thread) and `adapters/bluesky.py` (atproto, async): authenticate, publish to the account's own
timeline/feed, reply, favourite/boost or like/repost, read, and search. Self-identification is
enforced — Mastodon sets the account **bot flag** at connect; Bluesky records the automated
**self-label**. Bluesky requires an app password.

**M3 — X / Twitter.** `adapters/twitter.py` (tweepy v2, sync SDK wrapped in a worker thread):
authenticate, publish a tweet, reply, like/retweet, read a tweet, and recent search. Reads are
tier-sensitive — construct with `reads_enabled=False` (or expect 403s on the free tier), which turns
off the read/search capabilities up front so callers degrade gracefully.

Enable real adapters per platform via `ACCOUNT_POOL_REAL_ADAPTERS` (comma-separated, e.g.
`reddit,mastodon,bluesky,twitter`) and install the matching extras
(`pip install -e '.[reddit,mastodon,bluesky,twitter]'`); everything else stays on the `FakeAdapter`,
and `dry_run` still gates writes. Remaining adapters (Medium/Substack draft-only) land in a later
milestone. See `src/account_pool/adapters/`.

## Layout

```
src/account_pool/
  server/      # MCP server (FastMCP) — the agent-facing surface
  domain/      # Account / Action / Connection / ApprovalItem / AuditEvent + enums + contracts
  policy/      # the guard pipeline where every compliance boundary is enforced
  adapters/    # PlatformAdapter ABC + FakeAdapter (+ real adapters per milestone)
  vault/       # encrypted credential vault (secret-by-reference)
  db/          # SQLAlchemy persistence (SQLite v1 -> Postgres later)
  audit/ approvals/ actions/ scheduling/
tests/         # unit / integration / contract
```

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

# Generate a vault master key for local dev and export it
export ACCOUNT_POOL_MASTER_KEY="$(python -m account_pool.vault.keyref --generate)"

# Run the test suite (uses FakeAdapter + dry-run; touches no real platform)
pytest

# Run the MCP server over stdio (for an MCP client / Inspector)
account-pool-mcp
```

Copy `.env.example` to `.env` for configuration. The default is `DRY_RUN=true` — no adapter performs
a real network write until you explicitly disable it per environment.

## Agent integration

The server exposes MCP **tools** (mutations) and **resources** (read-only reflection). Start with the
`account_contract` tool / `contract://account/{platform}` resource — it returns the schema, allowed
verbs, and denial codes ("read first"). See the plan in the PR description for the full tool surface.
