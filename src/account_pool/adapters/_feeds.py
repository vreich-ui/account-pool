"""Tiny RSS/Atom feed parsing for the read-only (draft-only) platforms.

Medium and Substack have no usable write API for new integrations, but their public feeds make
*review* (reading recent posts) straightforward. The HTTP fetch is injectable so tests supply canned
feed XML and never hit the network.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def default_fetch(url: str) -> str:
    import httpx

    resp = httpx.get(url, follow_redirects=True, timeout=15.0, headers={"User-Agent": "account-pool/0.1"})
    resp.raise_for_status()
    return resp.text


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el: ET.Element, names: set[str]) -> str | None:
    for child in el:
        if _localname(child.tag) in names and child.text:
            return child.text.strip()
    return None


def _rss_item(item: ET.Element) -> dict[str, Any]:
    return {
        "title": _child_text(item, {"title"}),
        "link": _child_text(item, {"link", "guid"}),
        "author": _child_text(item, {"creator"}),  # dc:creator
        "published": _child_text(item, {"pubDate"}),
        "summary": (_child_text(item, {"description", "encoded"}) or "")[:500] or None,
    }


def _atom_entry(entry: ET.Element) -> dict[str, Any]:
    link = None
    for child in entry:
        if _localname(child.tag) == "link":
            link = child.get("href") or link
    return {
        "title": _child_text(entry, {"title"}),
        "link": link,
        "author": None,
        "published": _child_text(entry, {"published", "updated"}),
        "summary": (_child_text(entry, {"summary", "content"}) or "")[:500] or None,
    }


def parse_feed(xml_text: str, limit: int = 25) -> list[dict[str, Any]]:
    """Parse RSS 2.0 ``<item>`` or Atom ``<entry>`` elements into simple dicts."""
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for el in root.iter():
        tag = _localname(el.tag)
        if tag == "item":
            items.append(_rss_item(el))
        elif tag == "entry":
            items.append(_atom_entry(el))
        if len(items) >= limit:
            break
    return items
