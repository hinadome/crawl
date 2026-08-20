# Specific-URL crawl — task list

## Slice 1 — core

- [x] `crawler/url_list.py`: load `--url` / `--url-file`, normalize, filter scope
- [x] `Frontier.reprocess(urls)`
- [x] `Crawler`: `extra_urls`, `no_follow`, `reprocess_urls`; seed skip rule; skip `_enqueue_links` when no_follow

## Slice 2 — CLIs

- [x] Flags on `crawl_into_disk.py` and `crawl_into_db.py`
- [x] Wire into `Crawler(...)`

## Slice 3 — tests and docs

- [x] `--no-follow` + url list: only listed (and optional seed) pages stored
- [x] `--reprocess-url` resets done → pending and fetches again
- [x] Out-of-scope URL in list is skipped
- [x] README + CHANGELOG
- [x] Mark plan implemented
