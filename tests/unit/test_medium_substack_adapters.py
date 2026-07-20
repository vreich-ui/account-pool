"""Medium + Substack draft-only adapters: read via feeds, publish raises, feed-URL derivation."""

from __future__ import annotations

import pytest

from account_pool.adapters._feeds import parse_feed
from account_pool.adapters.base import AdapterSession, UnsupportedCapability
from account_pool.adapters.medium import MediumAdapter
from account_pool.adapters.medium import _feed_url as medium_feed
from account_pool.adapters.substack import SubstackAdapter
from account_pool.adapters.substack import _feed_url as substack_feed
from account_pool.domain.enums import LifecycleState, Platform, PublishMode
from account_pool.domain.models import Account, ContentDraft, TargetRef

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Brand Feed</title>
    <item>
      <title>First Post</title>
      <link>https://example.com/1</link>
      <dc:creator>Alice</dc:creator>
      <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
      <description>Hello world</description>
    </item>
    <item><title>Second Post</title><link>https://example.com/2</link></item>
  </channel>
</rss>"""

SAMPLE_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom Post</title>
    <link href="https://example.com/a"/>
    <updated>2026-01-01T00:00:00Z</updated>
    <summary>Atom summary</summary>
  </entry>
</feed>"""


def _session(platform: Platform, handle: str) -> AdapterSession:
    account = Account(
        account_id=f"acct_{platform.value}_x",
        platform=platform,
        handle=handle,
        status=LifecycleState.ACTIVE,
    )
    return AdapterSession(account=account, credentials={})


def test_parse_feed_rss_and_atom():
    rss = parse_feed(SAMPLE_RSS)
    assert len(rss) == 2
    assert rss[0]["title"] == "First Post"
    assert rss[0]["author"] == "Alice"
    assert rss[0]["summary"] == "Hello world"
    atom = parse_feed(SAMPLE_ATOM)
    assert atom[0]["title"] == "Atom Post" and atom[0]["link"] == "https://example.com/a"


def test_feed_url_derivation():
    assert medium_feed("@brand") == "https://medium.com/feed/@brand"
    assert medium_feed("brand") == "https://medium.com/feed/@brand"
    assert medium_feed("https://medium.com/feed/@x") == "https://medium.com/feed/@x"
    assert substack_feed("brandpub") == "https://brandpub.substack.com/feed"
    assert substack_feed("https://x.substack.com") == "https://x.substack.com/feed"
    assert substack_feed("https://x.substack.com/feed") == "https://x.substack.com/feed"


def test_capabilities_are_draft_only():
    m = MediumAdapter().capabilities()
    assert m.publish_mode == PublishMode.DRAFT_ONLY
    assert m.can_read is True and m.can_comment is False and m.can_react is False
    s = SubstackAdapter().capabilities()
    assert s.publish_mode == PublishMode.MANUAL
    assert s.can_read is True and s.can_comment is False


async def test_publish_raises_no_live_write():
    draft = ContentDraft(draft_id="d", account_id="a", body="x", title="t")
    with pytest.raises(UnsupportedCapability):
        await MediumAdapter().publish(_session(Platform.MEDIUM, "brand"), draft, dry_run=False)
    with pytest.raises(UnsupportedCapability):
        await SubstackAdapter().publish(_session(Platform.SUBSTACK, "brand"), draft, dry_run=False)


async def test_read_parses_feed():
    adapter = MediumAdapter(feed_fetcher=lambda url: SAMPLE_RSS)
    target = await adapter.resolve_target(_session(Platform.MEDIUM, "brand"), "@brand")
    assert target.raw == "https://medium.com/feed/@brand"
    res = await adapter.read(_session(Platform.MEDIUM, "brand"), target)
    assert len(res.items) == 2 and res.items[0]["title"] == "First Post"

    sub = SubstackAdapter(feed_fetcher=lambda url: SAMPLE_RSS)
    starget = await sub.resolve_target(_session(Platform.SUBSTACK, "brand"), "brandpub")
    assert starget.raw == "https://brandpub.substack.com/feed"
    sres = await sub.read(_session(Platform.SUBSTACK, "brand"), starget)
    assert len(sres.items) == 2


async def test_read_target_via_wrong_field_ignored():
    adapter = SubstackAdapter(feed_fetcher=lambda url: SAMPLE_RSS)
    res = await adapter.read(
        _session(Platform.SUBSTACK, "brand"),
        TargetRef(raw="https://brand.substack.com/feed", resolved=True),
    )
    assert res.detail["feed"] == "https://brand.substack.com/feed"
