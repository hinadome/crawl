# Specific-URL crawl — implementation plan

This plan has been implemented. See `--url`, `--url-file`, `--no-follow`, `--reprocess-url` on both crawl CLIs, and `URL_TARGETS_TASK.md`.

Add targeted URL processing to both `crawl_into_disk.py` and `crawl_into_db.py`, using the existing frontier.

## Goal

1. Enqueue specific URLs (`--url`, `--url-file`) into the same crawl.
2. Optionally fetch **only** those URLs (`--no-follow`).
3. Re-fetch URLs already in the frontier (`--reprocess-url`) without wiping the whole crawl.

## CLI (both scripts)

| Flag | Meaning |
|---|---|
| `--url URL` | Repeatable. Extra URLs to enqueue at depth 0. |
| `--url-file PATH` | One URL per line (`#` comments and blanks ignored). |
| `--no-follow` | Do not enqueue discovered links after a successful fetch. |
| `--reprocess-url URL` | Repeatable. Force URL to `pending` (insert if missing) so workers fetch it again. |

`start_url` remains required: it defines host scope (`seed_host`) and seed meta.

### Seed enqueue rules

- **New crawl:** enqueue `start_url` unless `--no-follow` **and** at least one extra URL was provided (then `start_url` is scope-only).
- **Resume:** do not re-enqueue seed; still apply `--url` / `--url-file` / `--reprocess-url`.
- Extra URLs must pass `should_enqueue` (same host / subdomain policy). Out-of-scope URLs are printed and skipped.
- After `_prepare_frontier`: enqueue extras (`ON CONFLICT DO NOTHING`), then `reprocess` listed URLs.

### Crawler / frontier

- `Crawler(..., extra_urls=..., no_follow=..., reprocess_urls=...)`
- `_enqueue_links`: return immediately if `no_follow`
- `Frontier.reprocess(urls)`: set `status=pending`, `attempts=0`, clear error; insert depth 0 if absent
- Sitemap still runs when `--sitemap` (and not already seeded); with `--no-follow`, sitemap URLs are fetched but their links are not followed

## Files

- `crawler/frontier.py` — `reprocess`
- `crawler/crawler.py` — params + seed/extra/reprocess + no_follow
- `crawler/url_list.py` — load/normalize URL lists (shared)
- `crawl_into_disk.py` / `crawl_into_db.py` — flags
- `tests/test_url_targets.py`
- README + CHANGELOG

## Examples

```bash
# Only these pages
uv run python crawl_into_disk.py https://example.com \
  -o scraped_output --url-file docs.txt --no-follow --content main

# Full crawl + guarantee these URLs
uv run python crawl_into_db.py https://example.com -f crawl_data.db \
  --url https://example.com/must-have -d 3

# Refresh one page after extractor change
uv run python crawl_into_disk.py https://example.com -o scraped_output \
  --reprocess-url https://example.com/docs/install --no-follow
```

## Out of scope

- Off-domain allowlist
- Separate `fetch_url.py` CLI
