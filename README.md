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

Writes page files under `scraped_output/`, frontier state in `scraped_output/crawl_state.db`, and `manifest.json` when the run finishes. By default (`--content main`) saved markdown keeps the **main body** (via Trafilatura / `main`/`article`) and drops nav/footer chrome. Use `--content full` for the previous whole-page behavior, or `--content selector --content-selector "main, .docs-body"` for a site-specific CSS region. Links are still discovered from the full HTML.

### Why files are split into subdirectories

Disk output is **not** a folder tree that matches the site URL. Each page is saved as:

`output_dir / <first 2 hex chars of URL hash> / <16-char hash>_<slug>.md`

Example: `scraped_output/a3/a3f1c9e2b4d0abcd_docs_getting-started.md`

- **Two-character subdirectory:** a large crawl would otherwise dump thousands of files into one folder, which slows listings, backups, and some filesystems. Sharding by `hash[:2]` spreads files across up to 256 directories (`00`–`ff`).
- **Hash in the filename:** using the raw URL as the name hits path-length limits, and stripping unsafe characters can make different URLs collide. The hash is a stable unique id; the slug is only so you can guess the page at a glance.
- **Finding a page by URL:** do not expect `docs/api/v1/page.md`. Use `lookup_crawl.py` (see [Inspect crawl state](#inspect-crawl-state)), or read `manifest.json` / `crawl_state.db` (`url` → `filepath`).

### Focused page content

Saved files use **main-content extraction** by default so markdown is useful for reading and RAG:

| Mode | Flag | Behavior |
|---|---|---|
| `main` (default) | `--content main` | Trafilatura main text; if too short, try `article` / `main` / `[role=main]`; then strip `nav`/`header`/`footer`/`aside`; else full cleaned body |
| `full` | `--content full` | Whole page after removing only `script` / `style` / `noscript` (old behavior) |
| `selector` | `--content selector --content-selector CSS` | Best matching CSS node (e.g. `.markdown-body`) |

Frontier link discovery always uses the **full** HTML, so menus still contribute crawl URLs even when they are omitted from the saved body. Re-crawl with `--force-new` (or a new `-o` / `-f`) to refresh already-saved pages under the new extractor.

### Specific URLs (disk and SQLite)

Both crawl scripts accept the same targeting flags:

```bash
# Only these pages (start_url sets host scope; not fetched when --no-follow + targets)
uv run python crawl_into_disk.py https://example.com \
  -o scraped_output --url-file docs.txt --no-follow --content main

uv run python crawl_into_db.py https://example.com -f crawl_data.db \
  --url https://example.com/a --url https://example.com/b --no-follow

# Full crawl, but also guarantee these URLs are in the frontier
uv run python crawl_into_disk.py https://example.com -o scraped_output \
  --url-file must_have.txt -d 3 -p 500

# Refresh one page in an existing crawl (e.g. after --content main)
# On a large resume, set -p above the current done count or use --drain-pending
uv run python crawl_into_disk.py https://example.com -o scraped_output \
  --reprocess-url https://example.com/docs/install --no-follow --drain-pending
```

`docs.txt` format: one URL per line; blank lines and `#` comments ignored. Out-of-scope hosts are skipped with a log line.

`--url` / `--url-file` only **enqueue** (`ON CONFLICT DO NOTHING`); they do not re-fetch already-`done` URLs. Use `--reprocess-url` to force `pending` again. Reprocess does not fetch by itself: a worker must **claim** the row (`pending` → `in_progress` → `done`). Claiming stops when `done + in_progress >= --max-pages`. On a large resume (thousands already `done`), either raise `-p` above the current `done` count or use `--drain-pending` (below).

## SQLite crawl

```bash
uv run python crawl_into_db.py https://example.com -f crawl_data.db -t markdown -d 3 -p 200 -c 4
```

Stores `crawl_state`, `crawl_meta`, and `scraped_pages` in the same database file.

## Resume

Re-run the same command with the same `-o` / `-f` path. URLs left `in_progress` are reset to `pending` and the frontier continues. If that database already belongs to a different seed URL, the process exits unless you pass `--force-new` (wipes that state and starts over).

A crawl prints `[STATS] pending=… done=…` on start/end. For inspection without starting workers, use the helpers below. Default `-p 500` is an absolute cap on `done` pages: if you already have more than 500 `done`, a resume with the default exits without claiming pending unless you raise `-p` or pass `--drain-pending`.

## Inspect crawl state

### Queue counts — `crawl_status.py`

Shows frontier totals (`pending`, `in_progress`, `done`, `failed`, `skipped`, `skipped_depth`) from disk or SQLite crawl state:

```bash
uv run python crawl_status.py -o scraped_output
uv run python crawl_status.py -f crawl_data.db
uv run python crawl_status.py -o scraped_output --format json
```

Defaults to `-o scraped_output` when neither `-o` nor `-f` is set. Library: `from crawler.status import frontier_status`.

#### How to read the counts

Example:

```text
total:           24615
pending:         0
in_progress:     0
done:            12000
failed:          25
skipped:         149
skipped_depth:   12441
```

| Status | Meaning |
|---|---|
| `done` | Fetched and stored (file on disk or row in `scraped_pages`). This is the crawl yield. |
| `failed` | Fetch attempted but gave up (timeouts, HTTP errors, WAF, retries exhausted). |
| `skipped` | Known but not fetched for policy reasons (usually `robots.txt`). |
| `skipped_depth` | Discovered from links, but deeper than `--max-depth` (default 3), so recorded and never fetched. |
| `pending` | Queued, waiting to be claimed by a worker. |
| `in_progress` | Claimed by a worker right now (orphans reset to `pending` on the next resume). |

`total` is **every URL ever inserted into the frontier**, not “pages downloaded”:

```text
total = done + failed + skipped + skipped_depth + pending + in_progress
```

So `total` can be much larger than `done`. A large `skipped_depth` means the site’s link graph extends past `-d`; raise `--max-depth` (and usually `-p` or `--drain-pending`) if you want those URLs fetched. `-p` / `--max-pages` caps **`done`** only — it does not stop deeper URLs from being recorded as `skipped_depth`.

`pending=0` and `in_progress=0` means the claimable queue is empty (a drained or finished run).

### Drain pending queue — `--drain-pending`

After targets/reprocess are applied, the crawler raises `--max-pages` to `done + pending + in_progress` so every currently pending URL can be claimed. Logs `[DRAIN] pending=… done=… → max_pages=…`. Prefer `--no-follow` so link discovery does not grow the queue while draining.

```bash
# 1) See how much is queued
uv run python crawl_status.py -o scraped_output

# 2) Fetch everything currently pending (disk)
uv run python crawl_into_disk.py https://example.com -o scraped_output \
  --drain-pending --no-follow -c 4

# Same for SQLite crawl
uv run python crawl_into_db.py https://example.com -f crawl_data.db \
  --drain-pending --no-follow -c 4

# Reprocess one URL, then drain so it actually runs on a large resume
uv run python crawl_into_disk.py https://example.com -o scraped_output \
  --reprocess-url https://example.com/docs/install \
  --drain-pending --no-follow
```

Library helper: `from crawler.status import drain_max_pages` (used by `Crawler` when `drain_pending=True`).

### URL → disk path — `lookup_crawl.py`

Resolves one URL against a disk crawl output dir: frontier status, recorded `filepath`, expected hash path, and whether the file exists (`ok` when status is `done` and the file is present):

```bash
uv run python lookup_crawl.py "https://example.com/docs/page" -o scraped_output
uv run python lookup_crawl.py "https://example.com/docs/page" -o scraped_output --strict
uv run python lookup_crawl.py "https://example.com/docs/page" -o scraped_output --format json
```

`--strict` exits `1` unless `ok`. Library: `from crawler.lookup import lookup_disk_url`.

## Options

`start_url` is required on both scripts. Everything else is optional.

### Shared

| Flag | Default | Meaning |
|---|---|---|
| `start_url` | (required) | Seed URL. Only this host is crawled unless `--include-subdomains` is set. |
| `-t`, `--output-type` | `markdown` | Saved page format: `markdown`, `html`, or `json`. |
| `-d`, `--max-depth` | `3` | How far to follow links from the seed (`0` = seed page only). Deeper URLs are recorded as `skipped_depth` and not fetched. |
| `-p`, `--max-pages` | `500` | Cap on pages stored as `done`. Workers stop claiming when `done + in_progress >=` this value, even if more URLs are `pending`. On resume, set `-p` **above** the current `done` count (see `crawl_status.py`) or use `--drain-pending`, or nothing new is fetched. |
| `-c`, `--concurrency` | `2` | Number of worker tasks fetching in parallel. |
| `--delay` | `0.5` | Seconds to wait between request starts to the same host. |
| `--include-subdomains` | off | Also crawl hosts like `docs.example.com` when the seed is `example.com`. Off = exact host only. |
| `--ignore-robots` | off | Do not honor `robots.txt`. Disallowed paths are otherwise marked `skipped`. |
| `--sitemap` | off | Enqueue in-scope URLs from `/sitemap.xml` (and nested sitemap indexes). |
| `--stealth` | off | For Playwright fallback only: browser-like User-Agent and hide `navigator.webdriver`. |
| `--force-new` | off | Wipe existing crawl state for this output path / database and start a new crawl. |
| `--content` | `main` | How to extract **saved** body text: `main` (Trafilatura + semantic fallback, default), `full` (whole page minus script/style), or `selector` (CSS). Link discovery still uses the full page. |
| `--content-selector` | | CSS selector when `--content selector` (e.g. `main, article, .markdown-body`). |
| `--url` | | Extra URL to crawl at depth 0 (repeatable). |
| `--url-file` | | File of URLs (one per line; `#` comments allowed). |
| `--no-follow` | off | Do not enqueue discovered links. With target URLs, `start_url` is used only for host scope (not fetched on a fresh crawl). |
| `--reprocess-url` | | Force an existing (or new) URL back to `pending` so it can be fetched again (repeatable). Still subject to `-p` unless `--drain-pending`; use `lookup_crawl.py` / `crawl_status.py` to verify. |
| `--drain-pending` | off | After enqueue/reprocess, raise `-p` to `done + pending + in_progress` so the whole pending queue can be claimed. Prefer with `--no-follow` on large resumes. |
| `-h`, `--help` | | Print usage and exit. |

### Disk only (`crawl_into_disk.py`)

| Flag | Default | Meaning |
|---|---|---|
| `-o`, `--output-dir` | `scraped_output` | Directory for page files, `crawl_state.db`, and `manifest.json`. |

### SQLite only (`crawl_into_db.py`)

| Flag | Default | Meaning |
|---|---|---|
| `-f`, `--db-file` | `crawl_data.db` | SQLite file for frontier state and `scraped_pages` content. |

## RAG for agents

After a crawl, `ingest_rag.py` turns pages into an embedding index. `query_rag.py` takes a question and prints ranked **chunks** as JSON. Neither script calls a chat LLM; your agent (or another app) uses the hits as context and should cite `hits[].url`.

Prefer crawling with `-t markdown`. HTML and JSON crawls still work: ingest converts HTML to markdown, and JSON uses the `markdown` field inside each payload.

Use the **same** `--persist-dir`, `--store`, and `--embedder` for ingest and query. `--embedder hash` is for tests only. Production: `--embedder local` (downloads `BAAI/bge-small-en-v1.5` once) or `--embedder openai` (`OPENAI_API_KEY`).

### From files (disk crawl)

1. Crawl to a directory. That run must finish far enough to write `manifest.json` (it is written when the crawler closes).

```bash
uv run python crawl_into_disk.py https://example.com -o scraped_output -t markdown -d 3 -p 200
```

2. Ingest reads **`scraped_output/manifest.json`**, not the hashed folder names. Each row has `url`, `filepath`, `format`. For every row, ingest opens that file, converts it to markdown if needed, and keys the document by **URL**.

3. Each page is split into chunks (default recursive, ~512 tokens with overlap). Title and URL are prepended before embedding. Vectors go to Chroma or Qdrant under `--persist-dir`. A sidecar `rag_index/catalog.db` stores URL, content hash, chunk text, and which `--store` last indexed that URL (for skip/re-ingest, BM25, and citations).

```bash
uv run python ingest_rag.py --from-disk scraped_output \
  --store chroma --persist-dir rag_index \
  --chunker recursive --embedder local --debug
```

4. Query embeds the question with the same model, retrieves nearest chunks (optionally hybrid BM25 + RRF, then optional rerank), and prints JSON. Parent-child ingest still returns the **parent** passage when a small child matches. Pass the same `--persist-dir` and `--store` you used at ingest.

```bash
uv run python query_rag.py "How do I install X?" \
  --persist-dir rag_index --store chroma --k 8 --hybrid
```

Re-run ingest after another crawl of the same `-o` directory: unchanged pages are skipped when content hash, chunker, embedder, **and store** all match. Changed pages are deleted from the active store and re-embedded. `--prune` also drops URLs that disappeared from the manifest. Add `--debug` to watch per-URL progress on stderr (`SKIP` / `INDEX` / `DONE` / `PRUNE`) while the final JSON summary still prints on stdout.

### From the database (SQLite crawl)

1. Crawl into SQLite. Page bodies live in **`scraped_pages`**, not in `crawl_state` (that table is only crawl progress).

```bash
uv run python crawl_into_db.py https://example.com -f crawl_data.db -t markdown -d 3 -p 200
```

2. Ingest selects `url`, `title`, `content`, `format`, `scraped_at` from `scraped_pages`. Conversion to markdown is the same as disk (markdown as-is, HTML converted, JSON uses `markdown`). Documents are still keyed by **URL**.

```bash
uv run python ingest_rag.py --from-sqlite crawl_data.db \
  --store chroma --persist-dir rag_index \
  --chunker recursive --embedder local --debug
```

3. Chunking, embedding, `catalog.db`, and the vector store are the **same pipeline** as disk. Only the reader differs (`--from-disk` vs `--from-sqlite`).

4. Query is identical: point at the same `--persist-dir`, `--store`, and embedder. The crawl DB is not opened at query time.

```bash
uv run python query_rag.py "How do I install X?" \
  --persist-dir rag_index --store chroma --k 8
```

Re-ingest the same `-f` file after a resumed crawl; hashes skip unchanged `scraped_pages` rows when the store also matches. `--prune` removes index entries for URLs no longer in `scraped_pages`. Use `--debug` the same way as disk ingest to verify skip vs re-index progress.

You can index disk output into one `--persist-dir` and DB output into another; do not mix two different crawls into one index unless you intend to merge those URL sets.

### Catalog vs Chroma / Qdrant

Under one `--persist-dir` (for example `rag_index/`):

| Path | Role | Shared across backends? |
|---|---|---|
| `catalog.db` | URL → hash, chunker, embedder, **store**, chunk text | Yes |
| `chroma/` | Dense vectors for `--store chroma` | No |
| `qdrant/` | Dense vectors for `--store qdrant` (local) | No |

Skip/resume only applies when the catalog row matches the **current** store. Switching `--store chroma` → `--store qdrant` (or the reverse) with the same `--persist-dir` re-embeds into the new backend. With `--debug` you should see `store-changed:chroma->qdrant` (or similar), not a mass of `SKIP` lines.

To keep both backends without re-embedding, use separate persist dirs:

```bash
uv run python ingest_rag.py --from-disk scraped_output --store chroma --persist-dir rag_index_chroma --embedder local
uv run python ingest_rag.py --from-disk scraped_output --store qdrant --persist-dir rag_index_qdrant --embedder local
```

Always query with the same `--store` and `--persist-dir` you ingested into.

### What ingest and query do (shared)

```
Crawl files or scraped_pages
        │
        ▼
   markdown pages (by URL)
        │
        ▼
   chunk → embed (title+URL+body)
        │
        ├──► vector store (rag_index/chroma or rag_index/qdrant)
        └──► catalog.db (hashes, chunk text, store name)
                    │
                    ▼
              query_rag.py / review_rag.py
                    │
                    ▼
         JSON hits for the agent
```

Ingest prints JSON counts on stdout: `seen`, `skipped`, `indexed`, `deleted`, `chunks`. With `--debug`, it also streams per-URL lines to stderr, for example:

```text
[ingest] start source=disk:scraped_output store=qdrant location=rag_index/qdrant ...
[ingest] SKIP  #1 https://example.com/a (indexed=0 skipped=1)
[ingest] INDEX #2 https://example.com/b (store-changed:chroma->qdrant)
[ingest] DONE  #2 https://example.com/b chunks=3 (indexed=1 skipped=1 total_chunks=3)
[ingest] finish seen=2 indexed=1 skipped=1 deleted=0 chunks=3
```

On the `start` line, `store=` is the backend and `location=` is where vectors are written (`rag_index/qdrant`, `rag_index/chroma`, or a `--qdrant-url`). `INDEX (... store-changed:...)` means the page was already in the catalog for another backend and is being written into the current one.

Query JSON:

```json
{
  "query": "How do I install X?",
  "hits": [
    {
      "text": "...",
      "url": "https://example.com/install",
      "title": "Install",
      "score": 0.81,
      "heading_path": "Install",
      "chunk_id": "...",
      "source": "dense"
    }
  ]
}
```

`source` is `dense`, `rrf` (hybrid), or `rerank`.

Implementations (swap without rewriting the pipeline): `rag/sources`, `rag/chunking`, `rag/embeddings`, `rag/stores`.

### Config file (`--config`)

`ingest_rag.py`, `query_rag.py`, and `review_rag.py` all accept `--config PATH`. Copy `rag.yaml.example` to `rag.yaml` (or any path) and edit. CLI flags override YAML when both are set.

Example:

```yaml
source:                    # ingest only
  type: disk               # disk | sqlite
  path: scraped_output

chunker:                   # ingest only
  type: recursive          # recursive | parent_child
  tokens: 512
  overlap: 64
  parent_tokens: 1024
  child_tokens: 160

embedder:                  # ingest, query, review
  type: local              # local | openai | hash
  model: BAAI/bge-small-en-v1.5

store:                     # ingest, query, review
  type: chroma             # chroma | qdrant
  persist_dir: rag_index
  collection: chunks
  # qdrant_url: http://localhost:6333

retrieve:                  # query, review (ingest ignores)
  k: 8
  hybrid: false
  rerank: false
  fetch_k: 20
  # rerank_model: BAAI/bge-reranker-base
```

| Section | Used by |
|---|---|
| `source`, `chunker` | `ingest_rag.py` only |
| `embedder`, `store` | ingest, query, and review |
| `retrieve` | `query_rag.py` and `review_rag.py` |

For review, `--config` does **not** crawl or re-ingest. It only sets how to open the existing index and how to retrieve (persist dir, store, embedder, k, hybrid, rerank). Point it at the same file you used for ingest so those settings stay aligned.

```bash
uv run python review_rag.py "How do I install X?" --config rag.yaml --compare
```

Review-only flags (`--compare`, `--gold`, `--expect-url`, `--strict`, `--format`, `--snippet-chars`) are CLI-only; they are not in the YAML.

### RAG options

| Flag | Default | Meaning |
|---|---|---|
| `--from-disk` | | Ingest a crawler output dir (`manifest.json` + files). |
| `--from-sqlite` | | Ingest `scraped_pages` from a crawl DB. |
| `--config` | | YAML defaults (`rag.yaml.example`). Shared by ingest/query/review. CLI overrides YAML. |
| `--store` | `chroma` | `chroma` or `qdrant`. Vectors live under `persist-dir/chroma` or `persist-dir/qdrant` (or `--qdrant-url`). Must match between ingest and query. |
| `--persist-dir` | `rag_index` | Holds `catalog.db` plus the store subdirectory. Same dir + different `--store` re-embeds; use separate dirs to keep both backends. |
| `--qdrant-url` | | Qdrant HTTP endpoint; omit to use a local path under `--persist-dir`. |
| `--chunker` | `recursive` | `recursive` (~512 tokens, 64 overlap) or `parent_child` (index small children, return parent text). |
| `--chunk-size` / `--chunk-overlap` | 512 / 64 | Recursive chunk size and overlap (tokens). |
| `--embedder` | `local` | `local`, `openai`, or `hash`. |
| `--embedder-model` | | Override model id. |
| `--force-reindex` | off | Re-embed even if content hash and store are unchanged. |
| `--prune` | off | Drop indexed URLs that disappeared from the crawl. |
| `--debug` | off | Print per-URL progress to stderr (`SKIP` / `INDEX` / `DONE` / `PRUNE`, including `store-changed`). Final JSON stats still go to stdout. |
| `-k` | 8 | Hits to return (`query_rag.py`). |
| `--hybrid` | off | Dense + BM25 fused with Reciprocal Rank Fusion. |
| `--rerank` | off | Cross-encoder rerank (`BAAI/bge-reranker-base`). |
| `--filter-url-prefix` | | Keep hits whose URL starts with this prefix. |

Pass `hits[].url` through in agent citations.

### Review retrieval

`query_rag.py` is for agents (JSON hits only). Use `review_rag.py` to inspect ranking quality: readable snippets, dense vs BM25 vs hybrid, and optional gold URLs.

```bash
# Defaults from rag.yaml (same store/embedder/persist_dir as ingest)
uv run python review_rag.py "How do I install X?" --config rag.yaml

# One question with explicit flags
uv run python review_rag.py "How do I install X?" \
  --persist-dir rag_index --store chroma --embedder local -k 8

# Side-by-side dense / BM25 / RRF
uv run python review_rag.py "How do I install X?" \
  --config rag.yaml --compare --format json

# Gold file (one JSON object per line)
uv run python review_rag.py --gold eval/queries.jsonl \
  --config rag.yaml -k 5 --strict
```

Gold JSONL:

```json
{"query": "How do I install X?", "expected_urls": ["https://example.com/install"]}
```

A gold URL matches if a hit URL equals it or starts with it (so `https://example.com/docs` matches `/docs/install`). Metrics: Hit@k, MRR, Recall@k. `--strict` exits 1 unless every gold query has a hit in top-k. `--expect-url` does the same for a single question. Index is read-only.

| Flag | Meaning |
|---|---|
| `--config` | YAML defaults for store / persist_dir / embedder / retrieve (see above). CLI overrides. |
| `--compare` | Show dense, BM25, and RRF (plus rerank if `--rerank`) |
| `--gold PATH` | JSONL of queries and expected URLs |
| `--expect-url` | Repeatable expected URL for one query |
| `--snippet-chars` | Snippet length in the text report (default 280) |
| `--format` | `text` (default) or `json` |
| `--strict` | Exit 1 if gold Hit@k < 1.0 |

## Tests

```bash
uv run pytest
```
