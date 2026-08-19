from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import html2text

from crawler.normalize import normalize_url

STRIP_TAGS = ("script", "style", "noscript")


def clean_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(list(STRIP_TAGS)):
        tag.extract()
    return str(soup)


def html_to_markdown(cleaned_html: str) -> str:
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_tables = False
    converter.body_width = 0
    return converter.handle(cleaned_html).strip()


def title_from_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def extractable_text_length(raw_html: str) -> int:
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(list(STRIP_TAGS)):
        tag.extract()
    return len(soup.get_text(" ", strip=True))


def looks_like_spa_shell(raw_html: str) -> bool:
    if not raw_html or not raw_html.strip():
        return True
    text_len = extractable_text_length(raw_html)
    soup = BeautifulSoup(raw_html, "lxml")
    has_scripts = bool(soup.find("script"))
    has_main = bool(soup.find(["article", "main"]))
    if text_len < 120 and has_scripts and not has_main:
        return True
    if len(raw_html) < 400 and has_scripts:
        return True
    return False


def render_content(output_type: str, url: str, raw_html: str, page_title: str) -> tuple[str, int]:
    cleaned_html = clean_html(raw_html)

    if output_type == "markdown":
        markdown_content = html_to_markdown(cleaned_html)
        content = f"<!-- Source: {url} -->\n# {page_title}\n\n{markdown_content}"
        return content, len(markdown_content)

    if output_type == "html":
        content = f"<!-- Source: {url} -->\n{cleaned_html}"
        return content, len(cleaned_html)

    if output_type == "json":
        import json

        markdown_content = html_to_markdown(cleaned_html)
        payload = {
            "url": url,
            "title": page_title,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "markdown": markdown_content,
            "cleaned_html": cleaned_html,
        }
        return json.dumps(payload, indent=2), len(markdown_content)

    raise ValueError(f"Unsupported output_type '{output_type}'")


def extract_hrefs(raw_html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(raw_html, "lxml")
    hrefs: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href")
        if not href:
            continue
        hrefs.append(normalize_url(urljoin(page_url, href)))
    return hrefs
