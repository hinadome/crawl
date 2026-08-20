from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import html2text

from crawler.normalize import normalize_url

STRIP_TAGS = ("script", "style", "noscript")
CHROME_TAGS = ("nav", "header", "footer", "aside", "form")
SEMANTIC_SELECTORS = ("article", "main", "[role=main]")
MIN_MAIN_CHARS = 200
CONTENT_MODES = ("main", "full", "selector")


def clean_html(raw_html: str, *, strip_chrome: bool = False) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    tags = list(STRIP_TAGS) + (list(CHROME_TAGS) if strip_chrome else [])
    for tag in soup(tags):
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


def _text_len(html: str) -> int:
    if not html or not html.strip():
        return 0
    soup = BeautifulSoup(html, "lxml")
    return len(soup.get_text(" ", strip=True))


def _trafilatura_html(raw_html: str) -> str | None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        extracted = trafilatura.extract(
            raw_html,
            include_comments=False,
            include_tables=True,
            include_links=True,
            output_format="html",
            favor_precision=True,
        )
    except Exception:
        return None
    if not extracted or not extracted.strip():
        return None
    return extracted


def _semantic_html(raw_html: str) -> str | None:
    soup = BeautifulSoup(raw_html, "lxml")
    for selector in SEMANTIC_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        for tag in node(list(STRIP_TAGS)):
            tag.extract()
        html = str(node)
        if _text_len(html) >= MIN_MAIN_CHARS:
            return html
    return None


def _selector_html(raw_html: str, selector: str) -> str | None:
    if not selector or not selector.strip():
        return None
    soup = BeautifulSoup(raw_html, "lxml")
    best: str | None = None
    best_len = 0
    for node in soup.select(selector):
        for tag in node(list(STRIP_TAGS)):
            tag.extract()
        html = str(node)
        length = _text_len(html)
        if length > best_len:
            best = html
            best_len = length
    if best is not None and best_len > 0:
        return best
    return None


def _is_usable(extracted: str | None, page_text_len: int) -> bool:
    if not extracted:
        return False
    length = _text_len(extracted)
    if length == 0:
        return False
    if page_text_len >= MIN_MAIN_CHARS * 2 and length < MIN_MAIN_CHARS:
        return False
    return True


def extract_main_html(
    raw_html: str,
    *,
    content_mode: str = "main",
    content_selector: str | None = None,
) -> str:
    mode = (content_mode or "main").lower().strip()
    if mode not in CONTENT_MODES:
        raise ValueError(
            f"Unsupported content_mode '{content_mode}'. Choose {', '.join(CONTENT_MODES)}."
        )
    if mode == "full":
        return clean_html(raw_html)

    page_text_len = extractable_text_length(raw_html)

    if mode == "selector":
        selected = _selector_html(raw_html, content_selector or "")
        if _is_usable(selected, page_text_len):
            return selected or clean_html(raw_html)
        # fall through to main-style fallbacks

    if mode in {"main", "selector"}:
        trafi = _trafilatura_html(raw_html)
        if _is_usable(trafi, page_text_len):
            return trafi or clean_html(raw_html)

        semantic = _semantic_html(raw_html)
        if _is_usable(semantic, page_text_len):
            return semantic or clean_html(raw_html)

        chrome_stripped = clean_html(raw_html, strip_chrome=True)
        if _is_usable(chrome_stripped, page_text_len):
            return chrome_stripped

    return clean_html(raw_html)


def render_content(
    output_type: str,
    url: str,
    raw_html: str,
    page_title: str,
    *,
    content_mode: str = "main",
    content_selector: str | None = None,
) -> tuple[str, int]:
    cleaned_html = extract_main_html(
        raw_html,
        content_mode=content_mode,
        content_selector=content_selector,
    )

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
            "content_mode": content_mode,
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
