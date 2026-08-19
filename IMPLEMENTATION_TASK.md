# Crawler reshape — implementation tasks

Single crawler core, two thin CLIs. SQLite frontier is the source of truth. Workers run in parallel. Timeouts fail a URL, not the process.

## Layout

```
scrapper/
  crawler/
    __init__.py
    normalize.py
    frontier.py
    politeness.py
    extract.py
    fetch.py
    sinks.py
    crawler.py
  crawl_into_disk.py
  crawl_into_db.py
```

Keep existing CLI flags (`start_url`, `-o`/`-f`, `-t`, `-d`, `-p`, `-c`). Add knobs only where new behavior needs them: `--include-subdomains`, `--delay`, `--ignore-robots`, `--force-new`, `--stealth`, `--sitemap`.

---

## Phase 0 — scaffolding

- [x] Add package `crawler/`.
- [x] Dependencies: `httpx`, `aiosqlite`, `lxml`.
- [x] Dev: `pytest`, `pytest-asyncio`.
- [x] Move shared helpers into modules; CLIs become thin wrappers.

**Done when:** both entry points import from `crawler`.

## Phase 1 — frontier as source of truth

Schema (disk crawler: `crawl_state.db` next to files; DB crawler: same file as content):

```
crawl_state (
  url TEXT PRIMARY KEY,
  canonical_url TEXT,
  depth INTEGER NOT NULL,
  status TEXT NOT NULL,          -- pending | in_progress | done | failed | skipped_depth | skipped
  http_status INTEGER,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  filepath TEXT,
  updated_at TEXT NOT NULL
)
crawl_meta (key TEXT PRIMARY KEY, value TEXT)
```

- [x] One long-lived `aiosqlite` connection; `journal_mode=WAL`; `synchronous=NORMAL`.
- [x] `ON CONFLICT DO NOTHING` for new pending URLs; first-seen depth wins.
- [x] Startup: `in_progress` → `pending` (orphan recovery).
- [x] Stop when no `pending` rows and `in_flight == 0`, or `done` count ≥ `max_pages`. Never `queue.empty()`.
- [x] Depth overflow: `status = skipped_depth`; do not requeue.
- [x] Resume: if DB has rows, resume that graph. If `start_url` differs from stored seed, fail unless `--force-new`.

**Done when:** resume + interrupt leave no stuck `in_progress` after restart.

## Phase 2 — real workers

- [x] `concurrency` worker tasks.
- [x] Claim next pending row in a transaction so two workers cannot take the same URL.
- [x] Per-URL timeout: catch `TimeoutError`, mark that URL, continue the worker.
- [x] Stats: `done` / `failed` / `skipped` / `in_flight` (do not mix failures into a “completed” counter).
- [x] Recycle browser context every N **done** Playwright pages behind a lock, only when no pages are open.

**Done when:** `-c 4` overlaps work; one hung page does not abort the process.

## Phase 3 — URL identity and domain policy

- [x] Strip fragment; lowercase host; drop default ports; consistent trailing-slash rule.
- [x] Drop tracking query keys (`utm_*`, `gclid`, `fbclid`, `ref`, …).
- [x] Default **exact host**. `--include-subdomains`: `host == seed or host.endswith('.' + seed)`.
- [x] Path-prefix denylist: `/login`, `/logout`, `/signin`, `/signup`, `/sso`, `/saml`.
- [x] Asset extension denylist; skip `mailto:`, `javascript:`, `tel:`.

**Done when:** `notexample.com` is out of scope; `/author` is not dropped.

## Phase 4 — retry and politeness

- [x] Retry timeouts and `429`/`503` with exponential backoff + `Retry-After` when present. Cap attempts (3). Other 4xx → `failed` immediately.
- [x] Fetch `/robots.txt`; skip disallowed paths unless `--ignore-robots`.
- [x] Per-host delay (`--delay`, default 0.5s) between request starts.
- [x] Optional `--sitemap`: parse `sitemap.xml` (and sitemap index) and enqueue in-scope URLs.

**Done when:** 429 does not permanently kill a URL on first hit; robots-disallowed URLs are `skipped` with a reason.

## Phase 5 — fetch strategy

- [x] `httpx` GET with an honest bot User-Agent; follow redirects; check final host.
- [x] If body looks like an SPA shell (tiny HTML / almost no text + scripts) → Playwright.
- [x] Playwright: abort images/fonts/analytics; `domcontentloaded`; no stealth unless `--stealth`.
- [x] Return `FetchResult(url, final_url, status, html, title, used_browser)`.

**Done when:** static HTML can crawl without Chromium for most pages; JS-heavy pages still work.

## Phase 6 — sinks and extract

- [x] Shared extract: markdown / html / json. Strip only `script` / `style` / `noscript` by default. Use `lxml`.
- [x] `FilesystemSink`: `output_dir / hash[:2] / {hash}_{slug}{ext}`; set frontier `filepath`; write `manifest.json` once on close.
- [x] `SqliteSink`: `scraped_pages` in the same DB file as the frontier.

**Done when:** disk and DB CLIs differ only by sink + path flags.

## Phase 7 — CLIs, docs, ignore rules

- [x] `crawl_into_disk.py` / `crawl_into_db.py`: argparse + `Crawler` + `asyncio.run`.
- [x] Delete the two large duplicated classes.
- [x] README: `uv sync`, `playwright install chromium`, examples, resume, new flags.
- [x] `.gitignore`: `scraped_output/`, `*.db`.

## Tests

- [x] `normalize`: suffix domain bug, tracking params, auth prefixes vs `/author`.
- [x] `frontier`: exclusive claim; orphan `in_progress` reset; depth skip.
- [x] `crawler` against a local HTTP server (no Playwright): workers, `max_pages`, timeout isolation.

## Out of scope

- Redis/Postgres frontier
- Per-page JSONL logging
- Content hashing / change detection
- Full robots `Crawl-delay` parser (simple disallow + `--delay` is enough)
