# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

#### Crawl inspection tools
- `crawl_status.py` — print frontier counts (`pending` / `in_progress` / `done` / `failed` / `skipped` / `skipped_depth`) from a disk crawl (`-o scraped_output` → `crawl_state.db`) or SQLite crawl DB (`-f`). Supports `--format json`. Library: `crawler.status.frontier_status`.
- `lookup_crawl.py` — map a URL to its on-disk location: frontier status, recorded `filepath`, expected `hash[:2]/hash_slug` path, `file_exists`, and `ok` (done + file present). `--strict` exits 1 unless ok; `--format json` for scripting. Library: `crawler.lookup.lookup_disk_url`.
- Tests: `tests/test_status.py`, `tests/test_lookup.py`.
- Docs: README “Inspect crawl state”.

#### Drain pending queue
- `--drain-pending` on `crawl_into_disk.py` / `crawl_into_db.py`: after `--url` / `--reprocess-url` are applied, raise `--max-pages` to `done + pending + in_progress` so the current pending queue can all be claimed (logs `[DRAIN] … → max_pages=…`).
- Prefer with `--no-follow` on large resumes so link discovery does not keep growing the queue.
- Library: `crawler.status.drain_max_pages`; `Crawler(..., drain_pending=True)`.
- Tests: `tests/test_url_targets.py` (`test_drain_pending_bypasses_small_max_pages`).
- Docs: README “Drain pending queue”.

#### Main-content extraction
- Default `--content main` on `crawl_into_disk.py` / `crawl_into_db.py`: Trafilatura extracts the page body before save; fallbacks are `article` / `main` / `[role=main]`, then strip `nav`/`header`/`footer`/`aside`, then full cleaned body.
- `--content full` restores whole-page save (script/style/noscript only removed).
- `--content selector --content-selector CSS` for site-specific regions (e.g. `main, .markdown-body`).
- Link discovery (`extract_hrefs`) still uses the **full** HTML so menus contribute crawl URLs even when omitted from saved markdown.
- Dependency: `trafilatura`.
- Tests: `tests/test_extract.py`.
- Docs/plans: README “Focused page content”; `CONTENT_EXTRACTION_IMPLEMENTATION_PLAN.md`, `CONTENT_EXTRACTION_TASK.md`.

#### Specific URL targets
- `--url` / `--url-file` enqueue depth-0 URLs on disk and SQLite crawls (`ON CONFLICT DO NOTHING` — does not re-fetch already-`done` URLs).
- `--no-follow` skips link enqueue; with targets, fresh crawls use `start_url` as host scope only.
- `--reprocess-url` forces URLs back to `pending` (insert if missing) for a refresh without `--force-new`; claiming still requires `done < --max-pages` unless `--drain-pending`.
- Shared helpers: `crawler/url_list.py`, `crawler/cli_urls.py`; `Frontier.reprocess`.
- Tests: `tests/test_url_targets.py`.
- Plan/tasks: `URL_TARGETS_IMPLEMENTATION_PLAN.md`, `URL_TARGETS_TASK.md`.

#### Crawler reshape
- Shared `crawler/` package: URL normalize, WAL SQLite frontier, politeness (`robots.txt`, delay, optional sitemap), HTTP-first fetch with Playwright fallback, extract, and disk/SQLite sinks.
- Thin CLIs `crawl_into_disk.py` and `crawl_into_db.py` with real worker concurrency (`-c`).
- Resume via frontier statuses (`pending` / `in_progress` / `done` / `failed` / `skipped` / `skipped_depth`); orphan `in_progress` reset on startup.
- Domain policy: exact host by default; `--include-subdomains`; path-prefix auth denylist (does not drop `/author`).
- CLI flags: `--delay`, `--ignore-robots`, `--force-new`, `--sitemap`, `--stealth`.
- Disk layout: `hash[:2]/hash_slug` files; `manifest.json` written once on close.
- Crawler tests (normalize, frontier, local HTTP server).

#### RAG pipeline
- `rag/` package with swappable sources, chunkers, embedders, and vector stores.
- `ingest_rag.py` — ingest from disk (`manifest.json`) or SQLite (`scraped_pages`).
- `query_rag.py` — agent-facing JSON hits with `url` / `title` / `score` (no chat LLM).
- Default stack: recursive markdown chunking (~512 / 64 tokens), Chroma or Qdrant, local BGE or OpenAI embeddings.
- Incremental ingest via `catalog.db` (skip unchanged URL + hash + chunker + embedder + **store**).
- Hybrid retrieval (BM25 + dense RRF) and optional cross-encoder rerank.
- Parent-child chunker option.
- Shared config: `rag.yaml.example` / `--config` for ingest, query, and review.
- `--debug` on ingest: per-URL progress on stderr (`SKIP` / `INDEX` / `DONE` / `PRUNE`, including `store-changed`).

#### Retrieval review
- `review_rag.py` — human/CI review of an existing index (read-only).
- Text or JSON reports with snippets and index stats.
- `--compare` for dense vs BM25 vs RRF (and rerank if enabled).
- Gold eval: `--gold` JSONL or `--expect-url`; Hit@k, MRR, Recall@k; `--strict`.

#### Docs and packaging
- Expanded `README.md` (crawler options, disk layout, focused content, specific URL targets, inspect crawl state, drain pending queue, RAG flows for file and DB, catalog vs Chroma/Qdrant, `--config` YAML, review).
- Plans/tasks: `IMPLEMENTATION_TASK.md`, `RAG_IMPLEMENTATION_PLAN.md`, `REVIEW_RAG_IMPLEMENTATION_PLAN.md`, `REVIEW_RAG_TASK.md`, `CONTENT_EXTRACTION_IMPLEMENTATION_PLAN.md`, `CONTENT_EXTRACTION_TASK.md`, `URL_TARGETS_IMPLEMENTATION_PLAN.md`, `URL_TARGETS_TASK.md`.
- Dependencies for crawler + RAG (httpx, aiosqlite, lxml, trafilatura, chromadb, qdrant-client, sentence-transformers, etc.).

### Fixed
- Crawler: serial “concurrency”, timeout aborting the whole run, suffix domain check, stats/`max_pages` accounting, resume seed mismatch (require `--force-new`).
- RAG: switching `--store` (Chroma ↔ Qdrant) with the same `--persist-dir` no longer mass-skips; catalog records store and re-embeds on `store-changed`.

### Changed
- Disk and DB crawl scripts no longer duplicate full crawler classes; they wrap the shared core.
- Prefer markdown crawl output (`-t markdown`) for RAG chunking quality.
- **Default saved crawl content is main-body focused** (`--content main`), not the full page. Use `--content full` for the previous behavior. Re-crawl with `--force-new` (or a new `-o`/`-f`) to refresh existing noisy files.

## [0.1.0] — 2026-08-19

### Added
- Initial resumable domain crawlers as separate scripts:
  - `crawl_into_disk.py` — pages to files + SQLite crawl state
  - `crawl_into_db.py` — pages + state in SQLite
- Playwright-based fetch, BeautifulSoup cleanup, markdown/html/json output types
- Basic depth/page limits and same-domain filtering
