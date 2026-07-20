"""The admin dashboard page, the new /platforms + /config endpoints, and enriched approvals."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from account_pool.domain.enums import Platform
from account_pool.server.rest_admin import build_admin_app
from account_pool.server.ui import render_page, sample_json
from account_pool.support import platform_overview, support_tier


def test_support_tiers():
    assert support_tier(Platform.REDDIT) == "live"
    assert support_tier(Platform.MEDIUM) == "draft_only"
    assert support_tier(Platform.SUBSTACK) == "manual"
    assert support_tier(Platform.YOUTUBE) == "planned"
    rows = platform_overview()
    assert len(rows) == len(list(Platform))
    assert {"platform", "tier", "publish_mode", "verbs"} <= set(rows[0])
    # live tiers sort first
    assert rows[0]["tier"] == "live"


def test_render_page_is_self_contained_html():
    page = render_page()
    assert page.startswith("<!doctype html>")
    assert "Needs you now" in page
    assert "Safe mode" in page  # the reassurance banner text
    assert "http://" not in page and "https://cdn" not in page  # no external assets
    assert len(sample_json()) > 100  # preview data available


def test_dashboard_and_new_endpoints_served(app):
    client = TestClient(build_admin_app(app))
    home = client.get("/")
    assert home.status_code == 200 and "text/html" in home.headers["content-type"]
    assert "Account Pool" in home.text

    cfg = client.get("/config").json()
    assert cfg["dry_run"] is True and cfg["environment"] == "dev"

    platforms = client.get("/platforms").json()
    assert len(platforms) == len(list(Platform))
    assert all("tier" in p for p in platforms)


def test_approvals_are_enriched_for_the_ui(app, make_active):
    async def _setup():
        a = await make_active(app, platform="mastodon", handle="brand")
        token = app.lock_service.checkout(a.account_id, "agent-1").lock.token
        d = app.action_service.create_draft(a.account_id, "helpful reply text")
        await app.action_service.comment("agent-1", a.account_id, token, "someone/status/9", d.draft_id)

    asyncio.run(_setup())
    client = TestClient(build_admin_app(app))
    approvals = client.get("/approvals").json()
    assert len(approvals) == 1
    view = approvals[0]
    assert view["platform"] == "mastodon"
    assert view["handle"] == "brand"
    assert view["verb"] == "comment"
    assert view["draft"]["body"] == "helpful reply text"
    assert view["expired"] is False
