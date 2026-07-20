"""M5 end-to-end: Medium (draft-only) + Substack (manual) through the full service pipeline."""

from __future__ import annotations

import pytest

from account_pool.adapters.medium import MediumAdapter
from account_pool.adapters.registry import default_registry
from account_pool.adapters.substack import SubstackAdapter
from account_pool.app import build_app
from account_pool.config import Settings
from account_pool.domain.enums import Platform

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>Recent Post</title><link>https://example.com/1</link><description>body</description></item>
</channel></rss>"""


def _registry():
    reg = default_registry()
    reg.register(Platform.MEDIUM, lambda: MediumAdapter(feed_fetcher=lambda url: SAMPLE_RSS))
    reg.register(Platform.SUBSTACK, lambda: SubstackAdapter(feed_fetcher=lambda url: SAMPLE_RSS))
    return reg


@pytest.fixture
def draft_app(master_key):
    return build_app(
        Settings(database_url="sqlite:///:memory:", dry_run=False, environment="dev"),
        registry=_registry(),
    )


async def _active(app, platform, handle):
    acc = app.account_service
    a = acc.register("agent-1", platform, handle)
    acc.authorize("agent-1", a.account_id, owner="k", consent_scope=["publish", "read"], attested_by="human")
    return await acc.connect("agent-1", a.account_id, "api_key", {"note": "draft-only"})


async def test_medium_publish_is_staged_and_read_works(draft_app):
    a = await _active(draft_app, "medium", "brandmedium")
    assert a.status.value == "active"
    token = draft_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = draft_app.action_service.create_draft(a.account_id, "long form body", title="My Article")
    published = await draft_app.action_service.publish("agent-1", a.account_id, token, d.draft_id)
    assert published.state.value == "done"
    assert published.result["detail"]["staged"] is True
    assert published.result["detail"]["title"] == "My Article"

    read = await draft_app.action_service.read("agent-1", a.account_id, "@brandmedium")
    assert read.state.value == "done"
    assert read.result["items"][0]["title"] == "Recent Post"


async def test_substack_publish_is_manual_stage(draft_app):
    a = await _active(draft_app, "substack", "brandletter")
    token = draft_app.lock_service.checkout(a.account_id, "agent-1").lock.token
    d = draft_app.action_service.create_draft(a.account_id, "newsletter body")
    published = await draft_app.action_service.publish("agent-1", a.account_id, token, d.draft_id)
    assert published.state.value == "done"
    assert published.result["detail"]["manual"] is True

    read = await draft_app.action_service.read("agent-1", a.account_id, "brandletter")
    assert read.result["items"][0]["title"] == "Recent Post"
