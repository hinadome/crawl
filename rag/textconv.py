from __future__ import annotations

import hashlib
import json
import re

from bs4 import BeautifulSoup
import html2text


def sha256_text(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def html_to_markdown(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_tables = False
    converter.body_width = 0
    return converter.handle(str(soup)).strip()


def strip_source_comment(text: str) -> str:
    return re.sub(r"^<!-- Source: .*? -->\n?", "", text.strip(), count=1)


def title_from_markdown(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def content_to_markdown(content: str, source_format: str, fallback_title: str = "") -> tuple[str, str]:
    fmt = (source_format or "markdown").lower()
    if fmt == "json":
        payload = json.loads(content)
        title = payload.get("title") or fallback_title
        markdown = payload.get("markdown") or html_to_markdown(payload.get("cleaned_html") or "")
        return title, markdown
    if fmt in {"html", "htm"}:
        markdown = html_to_markdown(strip_source_comment(content))
        return title_from_markdown(markdown, fallback_title), markdown
    markdown = strip_source_comment(content)
    return title_from_markdown(markdown, fallback_title), markdown


def embed_text_for(title: str, url: str, body: str) -> str:
    return f"Title: {title}\nURL: {url}\n\n{body}".strip()
