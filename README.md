# scrapper

Resumable crawler for a single seed URL. Pages are stored as files (`crawl_into_disk.py`) or in SQLite (`crawl_into_db.py`). Crawl progress lives in SQLite so a run can be interrupted and continued.

By default this is **not** a full-domain crawl. It stays on the seed host, follows links up to `--max-depth` (default 3), and stops after `--max-pages` stored pages (default 500).

## Setup

```bash
uv sync --group dev
uv run playwright install chromium
```

Chromium is only needed when a page looks like an empty JavaScript shell. Static HTML is fetched with `httpx` and User-Agent `ScrapperBot/0.1`.

## Disk crawl

```bash
uv run python crawl_into_disk.py https://example.com -o scraped_output -t markdown -d 3 -p 200 -c 4
```

Writes page files under `scraped_output/`, frontier state in `scraped_output/crawl_state.db`, and `manifest.json` when the run finishes.

### Why files are split into subdirectories

Disk output is **not** a folder tree that matches the site URL. Each page is saved as:

`output_dir / <first 2 hex chars of URL hash> / <16-char hash>_<slug>.md`

Example: `scraped_output/a3/a3f1c9e2b4d0abcd_docs_getting-started.md`

- **Two-character subdirectory:** a large crawl would otherwise dump thousands of files into one folder, which slows listings, backups, and some filesystems. Sharding by `hash[:2]` spreads files across up to 256 directories (`00`–`ff`).
- **Hash in the filename:** using the raw URL as the name hits path-length limits, and stripping unsafe characters can make different URLs collide. The hash is a stable unique id; the slug is only so you can guess the page at a glance.
- **Finding a page by URL:** use `manifest.json` or `crawl_state.db` (`url` → `filepath`). Do not expect `docs/api/v1/page.md`.

## SQLite crawl

```bash
uv run python crawl_into_db.py https://example.com -f crawl_data.db -t markdown -d 3 -p 200 -c 4
```

Stores `crawl_state`, `crawl_meta`, and `scraped_pages` in the same database file.

## Resume

Re-run the same command with the same `-o` / `-f` path. URLs left `in_progress` are reset to `pending` and the frontier continues. If that database already belongs to a different seed URL, the process exits unless you pass `--force-new` (wipes that state and starts over).

## Options

`start_url` is required on both scripts. Everything else is optional.

### Shared

| Flag | Default | Meaning |
|---|---|---|
| `start_url` | (required) | Seed URL. Only this host is crawled unless `--include-subdomains` is set. |
| `-t`, `--output-type` | `markdown` | Saved page format: `markdown`, `html`, or `json`. |
| `-d`, `--max-depth` | `3` | How far to follow links from the seed (`0` = seed page only). Deeper URLs are recorded as `skipped_depth` and not fetched. |
| `-p`, `--max-pages` | `500` | Maximum number of pages stored as `done`. The crawl stops when this count is reached, even if more links are queued. |
| `-c`, `--concurrency` | `2` | Number of worker tasks fetching in parallel. |
| `--delay` | `0.5` | Seconds to wait between request starts to the same host. |
| `--include-subdomains` | off | Also crawl hosts like `docs.example.com` when the seed is `example.com`. Off = exact host only. |
| `--ignore-robots` | off | Do not honor `robots.txt`. Disallowed paths are otherwise marked `skipped`. |
| `--sitemap` | off | Enqueue in-scope URLs from `/sitemap.xml` (and nested sitemap indexes). |
| `--stealth` | off | For Playwright fallback only: browser-like User-Agent and hide `navigator.webdriver`. |
| `--force-new` | off | Wipe existing crawl state for this output path / database and start a new crawl. |
| `-h`, `--help` | | Print usage and exit. |

### Disk only (`crawl_into_disk.py`)

| Flag | Default | Meaning |
|---|---|---|
| `-o`, `--output-dir` | `scraped_output` | Directory for page files, `crawl_state.db`, and `manifest.json`. |

### SQLite only (`crawl_into_db.py`)

| Flag | Default | Meaning |
|---|---|---|
| `-f`, `--db-file` | `crawl_data.db` | SQLite file for frontier state and `scraped_pages` content. |

## Tests

```bash
uv run pytest
```
