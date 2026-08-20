# RAG ingest/query — implementation plan

Separate from the crawler. Consume crawl **files** or **SQLite** and build a retrieval index for LLM/agent RAG. Chunking and vector stores are swappable via protocols.

This plan has been implemented. See `ingest_rag.py`, `query_rag.py`, and `rag/`.

---

## Goal

1. `ingest` crawled pages → chunks → embeddings → vector store.
2. `query` a question → ranked chunks with citations (`url`, `title`, `chunk_id`).
3. Swap **source**, **chunker**, **embedder**, **vector store**, and **retriever** without rewriting the pipeline.
4. Reflect current RAG practice: markdown-aware recursive chunks as default, rich metadata, incremental ingest, hybrid retrieval as the first upgrade — not a kitchen-sink stack on day one.

---

## What the crawl already gives you

| Sink | How to read |
|---|---|
| Disk | `manifest.json` + files (`markdown` / `html` / `json`) |
| SQLite | `scraped_pages` (`url`, `title`, `content`, `format`, `char_count`, `scraped_at`) |

Prefer **markdown** for chunking (headings survive). For `html`, convert to markdown at ingest. For `json`, use the `markdown` field inside the payload.

Do not embed from hashed filenames; always key documents by **canonical URL**.

---

## Research takeaways (2025–2026) to bake in

Consensus from production RAG writeups and recent chunking evaluations:

- **Default chunker:** recursive / structure-aware split on markdown headings → paragraphs → sentences, **~400–512 tokens**, **10–20% overlap**. Token-based splits stay competitive; “semantic chunking” is slower and often not worth it as a default ([Firecrawl 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag), [arXiv:2608.16586](https://arxiv.org/html/2608.16586v1)).
- **Highest-ROI retrieval upgrades (in order):** (1) metadata + title/url prepended to chunk text, (2) **hybrid dense + BM25 + RRF**, (3) **parent-child** (index small children, return parent), (4) cross-encoder **rerank** of top 20→5, (5) contextual/late chunking only if eval says so.
- **Same embedding model** for documents and queries. Instruction-tuned models may need `search_document:` / `search_query:` prefixes.
- **Vector DB:** Chroma/Qdrant embedded for local; Qdrant/pgvector/Weaviate when you need hybrid + filters in production. Do not couple the pipeline to LangChain’s store classes.
- **Agent use:** return structured hits (text + metadata + score), not a baked-in LLM answer. Generation stays in the agent.

Out of v1: GraphRAG, agentic multi-hop, Anthropic contextual retrieval, late chunking (need long-context embedders). Keep interfaces so those can be extra chunkers/retrievers later.

---

## Layout

```
rag/
  __init__.py
  types.py              # Document, Chunk, Hit
  sources/
    base.py             # Source protocol
    disk.py             # manifest.json + files
    sqlite.py           # scraped_pages
  chunking/
    base.py             # Chunker protocol
    recursive.py        # default: markdown recursive
    parent_child.py     # optional upgrade
  embeddings/
    base.py             # Embedder protocol (embed_docs, embed_query)
    openai.py
    local.py            # sentence-transformers / nomic-style
  stores/
    base.py             # VectorStore protocol
    chroma.py           # default local
    qdrant.py           # hybrid-capable backend
  retrieve/
    dense.py
    hybrid.py           # BM25 + dense + RRF
    rerank.py           # optional cross-encoder
  pipeline.py           # ingest + query orchestration
  config.py             # YAML/env-backed settings
ingest_rag.py           # CLI: crawl output → index
query_rag.py            # CLI: question → JSON hits (agent-friendly)
```

Keep crawler and RAG packages independent. RAG depends on crawl **output format**, not on `crawler` internals (optional small reader that understands `manifest.json` / `scraped_pages` only).

---

## Core types

```python
@dataclass
class Document:
    url: str
    title: str
    text: str                 # markdown
    content_hash: str
    source_format: str
    scraped_at: str | None
    extra: dict

@dataclass
class Chunk:
    chunk_id: str             # stable hash(url, index, text)
    url: str
    title: str
    text: str                 # what gets embedded (may include title prefix)
    index: int
    token_count: int
    heading_path: str | None  # e.g. "Install > macOS"
    parent_id: str | None     # parent-child chunker
    metadata: dict

@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str               # "dense" | "sparse" | "rrf" | "rerank"
```

**Embed text** = `Title: {title}\nURL: {url}\n\n{chunk}` (cheap “enriched title” pattern; strong baseline in recent evaluations).

---

## Protocols (swap points)

```python
class Source(Protocol):
    def iter_documents(self) -> Iterator[Document]: ...

class Chunker(Protocol):
    name: str
    def split(self, doc: Document) -> list[Chunk]: ...

class Embedder(Protocol):
    model_id: str
    dimensions: int
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def delete_by_url(self, url: str) -> None: ...
    def query(self, vector: list[float], k: int, where: dict | None) -> list[Hit]: ...
    # optional:
    def query_hybrid(...) -> list[Hit]: ...
```

Register implementations in a small factory (`--store chroma|qdrant`, `--chunker recursive|parent_child`, `--embedder openai|local`).

---

## Default stack (v1)

| Layer | Default | Why |
|---|---|---|
| Source | disk or sqlite (CLI flag) | Matches this repo |
| Chunker | recursive markdown, 512 tokens, 64-token overlap (~12%) | Best default cost/quality |
| Embedder | OpenAI `text-embedding-3-small` **or** local `BAAI/bge-small-en-v1.5` | Small, cheap; same model for query |
| Store | **Chroma** (persistent dir) | Zero extra infra |
| Retrieve | dense top-k + metadata filter | Simple, testable |
| Output | JSON hits for the agent | No LLM inside this script |

### v1.1 (same interfaces)

- **Qdrant** store (Docker or embedded) with payload indexes on `url`, `title`.
- **Hybrid:** BM25 (rank-bm25 or Qdrant sparse) + dense, fuse with **RRF**.
- **Parent-child chunker:** children ~128–200 tokens indexed; return parent ~512–1024 to the agent.

### Later (only if retrieval eval is weak)

- Cross-encoder rerank (`BAAI/bge-reranker-base`) on top 20.
- Contextual retrieval (LLM blurb per chunk).
- pgvector / Weaviate / Neo4j as additional `VectorStore`s.

---

## Incremental ingest (required)

Crawls resume; RAG ingest must too.

- Persist `{url, content_hash, chunker, embedder, chunk_ids}` in a small SQLite sidecar next to the index (or in store metadata).
- Unchanged hash → skip.
- Changed hash → `delete_by_url` then re-upsert.
- URLs removed from crawl (optional `--prune`) → delete from store.

This avoids re-embedding the whole site on every crawl.

---

## CLI

```bash
# Ingest from disk crawl
uv run python ingest_rag.py --from-disk scraped_output \
  --store chroma --persist-dir rag_index \
  --chunker recursive --embedder local

# Ingest from SQLite crawl
uv run python ingest_rag.py --from-sqlite crawl_data.db \
  --store qdrant --qdrant-url http://localhost:6333

# Query (agent / debugging)
uv run python query_rag.py "How do I install X?" \
  --persist-dir rag_index --k 8 --format json
```

Flags (planned): `--chunk-size`, `--chunk-overlap`, `--k`, `--hybrid`, `--rerank`, `--filter-url-prefix`, `--force-reindex`.

`query_rag.py` prints JSON:

```json
{
  "query": "...",
  "hits": [
    {"text": "...", "url": "...", "title": "...", "score": 0.81, "heading_path": "Install"}
  ]
}
```

The agent builds its own prompt from `hits`.

---

## Config

`rag.yaml` (optional) so agents/CI don’t need a long CLI:

```yaml
source: { type: disk, path: scraped_output }
chunker: { type: recursive, tokens: 512, overlap: 64 }
embedder: { type: local, model: BAAI/bge-small-en-v1.5 }
store: { type: chroma, persist_dir: rag_index }
retrieve: { k: 8, hybrid: false, rerank: false }
```

CLI overrides file.

---

## Testing

- Disk + SQLite sources against a tiny fixture crawl.
- Recursive chunker: headings don’t split mid-word; overlap exists; `chunk_id` stable.
- Incremental: second ingest of unchanged docs makes **zero** embed calls (mock embedder).
- Store round-trip: upsert → query returns the seeded chunk (Chroma).
- Hybrid RRF: unit-test fusion on two fake ranked lists.

No live OpenAI in CI.

---

## Implementation slices

1. **Types + Source (disk, sqlite) + recursive chunker + Chroma + local embedder + two CLIs.** Usable RAG for an agent.
2. **Incremental hash skip/delete.**
3. **Qdrant backend + hybrid RRF.**
4. **Parent-child chunker; optional rerank.**
5. README: ingest after crawl, env vars, how an agent should cite `url`.

Do not add LLM generation, chat UI, or GraphRAG in this script.

---

## Explicit non-goals

- Changing crawler output format (except documenting which `--output-type` is best: **markdown**).
- One mega LangChain `VectorstoreIndexCreator`.
- Storing raw HTML blobs in the vector DB (store markdown chunks + metadata only).

---

## Decision summary

| Decision | Choice |
|---|---|
| Default chunker | Markdown recursive, 512 / 64 tokens |
| Default store | Chroma (swap to Qdrant without pipeline changes) |
| Default embedder | Local bge-small, OpenAI optional |
| Retrieval v1 | Dense + title/url prefix on chunks |
| Next retrieval | Hybrid RRF, then parent-child, then rerank |
| Agent contract | JSON hits with `url` for citations |
