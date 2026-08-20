from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from crawler.extract import extract_hrefs
from crawler.lookup import (
    DbUrlLocation,
    DiskUrlLocation,
    format_db_lookup,
    format_disk_lookup,
    load_db_page_content,
    lookup_db_url,
    lookup_disk_url,
)
from crawler.normalize import normalize_url

# Markdown [text](url) and bare <http...> autolinks
_MD_LINK_RE = re.compile(
    r"\[(?:[^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
    r"|<(https?://[^>\s]+)>",
    re.IGNORECASE,
)


@dataclass
class PageLinks:
    url: str
    source: str | None
    store: str
    links: list[str]
    location: DiskUrlLocation | DbUrlLocation

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "source": self.source,
            "store": self.store,
            "links": self.links,
            "link_count": len(self.links),
            "location": self.location.as_dict(),
        }

    @property
    def source_path(self) -> str | None:
        """Backward-compatible alias for disk file path or sqlite source label."""
        return self.source


def _dedupe_preserve(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def extract_links_from_markdown(markdown: str, page_url: str) -> list[str]:
    found: list[str] = []
    for match in _MD_LINK_RE.finditer(markdown):
        target = match.group(1) or match.group(2)
        if not target or target.startswith("#"):
            continue
        if target.startswith(("mailto:", "javascript:", "data:")):
            continue
        found.append(normalize_url(urljoin(page_url, target)))
    # Also pick up HTML <a href> if markdownify left any tags
    if "<a " in markdown.lower():
        found.extend(extract_hrefs(f"<html><body>{markdown}</body></html>", page_url))
    return _dedupe_preserve(found)


def extract_links_from_content(content: str, page_url: str, *, kind: str) -> list[str]:
    """Extract absolute http(s) links from saved crawl content.

    ``kind`` is ``markdown``, ``html``, or ``json``.
    """
    kind = kind.lower()
    if kind in {"html", "htm"}:
        return _dedupe_preserve(extract_hrefs(content, page_url))
    if kind == "json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return extract_links_from_markdown(content, page_url)
        html = payload.get("cleaned_html") or ""
        if html:
            return _dedupe_preserve(extract_hrefs(html, page_url))
        md = payload.get("markdown") or ""
        return extract_links_from_markdown(md, page_url)
    # markdown (default)
    return extract_links_from_markdown(content, page_url)


def _kind_from_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".html", ".htm"}:
        return "html"
    if ext == ".json":
        return "json"
    return "markdown"


def list_links_from_disk_url(
    output_dir: str,
    url: str,
    *,
    output_type: str = "markdown",
) -> PageLinks:
    """Resolve a crawled URL on disk and list links found in its saved content."""
    loc = lookup_disk_url(output_dir, url, output_type=output_type)
    path = loc.filepath if loc.filepath and os.path.isfile(loc.filepath) else None
    if path is None and os.path.isfile(loc.expected_filepath):
        path = loc.expected_filepath
    if path is None:
        return PageLinks(url=url, source=None, store="disk", links=[], location=loc)

    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    links = extract_links_from_content(content, loc.normalized_url, kind=_kind_from_path(path))
    return PageLinks(url=url, source=path, store="disk", links=links, location=loc)


def list_links_from_db_url(db_path: str, url: str) -> PageLinks:
    """Resolve a URL in a SQLite crawl DB and list links from scraped_pages.content."""
    loc = lookup_db_url(db_path, url)
    loaded = load_db_page_content(db_path, url)
    if loaded is None:
        return PageLinks(
            url=url,
            source=None,
            store="sqlite",
            links=[],
            location=loc,
        )
    normalized, content, kind = loaded
    links = extract_links_from_content(content, normalized, kind=kind)
    source = f"sqlite:{os.path.abspath(db_path)}#scraped_pages"
    return PageLinks(url=url, source=source, store="sqlite", links=links, location=loc)


def format_page_links(result: PageLinks, *, include_location: bool = False) -> str:
    lines: list[str] = []
    if include_location:
        if isinstance(result.location, DbUrlLocation):
            lines.append(format_db_lookup(result.location).rstrip())
        else:
            lines.append(format_disk_lookup(result.location).rstrip())
        lines.append("")
    lines.append(f"store:      {result.store}")
    lines.append(f"source:     {result.source}")
    lines.append(f"link_count: {len(result.links)}")
    lines.append("links:")
    if not result.links:
        lines.append("  (none)")
    else:
        for link in result.links:
            lines.append(f"  {link}")
    return "\n".join(lines) + "\n"
