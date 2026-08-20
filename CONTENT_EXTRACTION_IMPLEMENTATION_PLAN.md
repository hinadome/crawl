# Main-content extraction — implementation plan

This plan has been implemented. See `--content` on the crawl CLIs, `crawler/extract.py`, and `CONTENT_EXTRACTION_TASK.md`.

Focused body text in saved crawl output (markdown/html/json), without dropping link discovery.

## Problem

`clean_html` only removes `script` / `style` / `noscript`. Nav, header, footer, and sidebars remain, so `.md` files are noisy for reading and RAG.

## Goal

1. Extract **main content** when saving pages.
2. Keep **full-page HTML** for `extract_hrefs` (frontier).
3. Modes: `main` (default), `full` (current behavior), `selector` (CSS).
4. Safe fallback if main extract is too short.

## Design

```
raw HTML
  ├─ extract_hrefs(full page)           → frontier (unchanged)
  └─ extract_for_save(mode) → body HTML → render_content → sink
```

### Modes

| Mode | Behavior |
|---|---|
| `main` | Trafilatura (`output_format` markdown/html as needed). If empty or &lt; ~200 chars while page has substantial text → semantic fallback (`article` / `main` / `[role=main]`) → strip chrome tags → else full body. |
| `full` | Current: strip only script/style/noscript. |
| `selector` | CSS selector via BeautifulSoup `select`; first match with enough text wins; else fallback like `main`. |

### CLI

Both crawl scripts:

```
--content {main,full,selector}   default: main
--content-selector CSS           required when --content selector
```

Pass through `Crawler` → sinks → `render_content(..., content_mode=..., content_selector=...)`.

### Files

- `crawler/extract.py` — `extract_main_html`, mode dispatch, Trafilatura + semantic fallback
- `crawler/sinks.py` — accept mode/selector on constructors
- `crawler/crawler.py` — optional; sinks own the mode (cleaner)
- `crawl_into_disk.py` / `crawl_into_db.py` — flags
- `tests/test_extract.py` — nav/main fixture
- README + CHANGELOG
- `pyproject.toml` — `trafilatura`

### Out of scope

- Re-extracting already-saved `.md` files
- LLM-based extraction
- Changing RAG ingest (cleaner crawl input is enough)

## Success

A page with `<nav>…</nav><main><h1>Title</h1><p>Body</p></main>` saves body-focused markdown under `--content main`, and still discovers links from nav under the same crawl.
