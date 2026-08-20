# Retrieval review script — implementation plan

This plan has been implemented. See `review_rag.py`, `rag/review.py`, and `REVIEW_RAG_TASK.md`.

`query_rag.py` is the **agent contract**: one retriever config → JSON hits. This new script is for **humans** (and CI) to inspect whether retrieval is any good before wiring an agent.

---

## Goal

A separate CLI, `review_rag.py`, that:

1. Runs a question against an existing `--persist-dir` index.
2. Prints a readable report (rank, score, URL, title, heading, snippet).
3. Optionally **compares** dense vs BM25 vs hybrid (RRF) vs rerank on the same query.
4. Optionally scores a **gold file** of `{query, expected_urls}` with Hit@k / MRR.
5. Reuses `rag/` (catalog, embedder, store, retrieve). Does not duplicate ingest. Does not call a chat LLM.

---

## Why not extend `query_rag.py`

| | `query_rag.py` | `review_rag.py` |
|---|---|---|
| Audience | Agent / pipeline | Developer reviewing quality |
| Output | Compact JSON hits | Annotated report + optional JSON |
| Retrievers | One config | Side-by-side channels |
| Metrics | None | Hit@k, MRR, overlap between channels |
| Extra context | Chunk text only | Snippet + catalog stats + missing gold URLs |

Keep `query_rag.py` stable for agents. Review belongs in its own script.

---

## Layout

```
rag/
  review.py          # report builders, compare, metrics (no CLI)
review_rag.py        # argparse
tests/test_rag_review.py
```

No new vector store. Read-only on the index.

---

## Commands

```bash
# Single query, human report
uv run python review_rag.py "How do I install X?" \
  --persist-dir rag_index --k 8 --embedder local

# Same query, show dense / bm25 / hybrid / rerank columns
uv run python review_rag.py "How do I install X?" \
  --persist-dir rag_index --compare --k 8

# Batch gold evaluation
uv run python review_rag.py --gold eval/queries.jsonl \
  --persist-dir rag_index --k 5 --format json
```

Shared flags with query: `--config`, `--persist-dir`, `--store`, `--qdrant-url`, `--embedder`, `--embedder-model`, `-k`, `--filter-url-prefix`, `--hybrid`, `--rerank`.

Review-only:

| Flag | Meaning |
|---|---|
| `--compare` | Run dense, BM25, RRF (and rerank if `--rerank`) and print a comparison table |
| `--gold PATH` | JSONL: `{"query": "...", "expected_urls": ["https://..."]}` (prefix match allowed) |
| `--snippet-chars` | Truncate body in the text report (default 280) |
| `--format` | `text` (default) or `json` |
| `--expect-url` | Repeatable; treat as gold URLs for a single query |

---

## Report contents

### Text (default)

```
Index: rag_index  store=chroma  embedder=local  docs=120  chunks=840
Query: How do I install X?

#  score   src    title                         url
1  0.812   dense  Install                       https://example.com/install
   heading: Install > pip
   snippet: pip install acme ...

2  ...
```

`--compare` adds per-channel rank lists and **overlap** (Jaccard of top-k URLs between dense and hybrid). Call out chunks that BM25 found and dense missed (typical “exact token” wins).

### JSON

Machine-readable version of the same: `index`, `query`, `channels: {dense, bm25, rrf, rerank}`, `hits`, `metrics` (if gold).

---

## Gold metrics (when `--gold` or `--expect-url`)

For each query, a gold URL **hits** if any returned hit URL equals it or **starts with** it (prefix), so `https://example.com/docs` matches section pages.

- **Hit@k:** fraction of queries with ≥1 gold URL in top-k
- **MRR:** mean reciprocal rank of the first gold URL
- **Recall@k:** gold URLs found / gold URLs listed (micro or per-query then macro)

Print a one-line summary plus per-query missed URLs. Exit code `1` if `--gold` and Hit@k is 0 (optional `--fail-under 0.5` later; v1: always 0 unless `--strict`).

v1 `--strict`: exit 1 when Hit@k < 1.0 on the gold file.

---

## Implementation notes

- Extract **channel retrieval** from `pipeline.query` (or add `query_channels(config, question) -> dict[str, list[Hit]]`) so review can request dense/BM25/RRF without three full embed calls. Embed the query **once**.
- BM25 already lives in `HybridRetriever`; expose `bm25_rank` hits via catalog hydrate.
- Index stats: `SELECT COUNT(*) FROM documents/chunks` on `catalog.db`.
- Snippets: first `--snippet-chars` of `chunk.text`, collapse whitespace; do not dump huge parent chunks in text mode.
- Do not open crawl disk/SQLite; review is index-only.

---

## Tests

- Comparison JSON contains `dense` and `bm25` keys on a tiny hash-embedder index.
- Gold: one query whose expected URL is in top-k → Hit@k = 1; a miss → Hit@k = 0.
- Text report includes URL and snippet (string check).
- No live OpenAI / no CrossEncoder download unless `--rerank` in a skipped test.

---

## Out of scope

- LLM-as-judge / faithfulness (RAGAS)
- Web UI
- Changing `query_rag.py` output shape
- Re-embedding or writing to the vector store

---

## Slice

1. `query_channels` + `review_rag.py` text/json for one query + catalog stats.
2. `--compare` overlap.
3. `--gold` / `--expect-url` Hit@k + MRR + `--strict`.
4. README: “Review retrieval” under the RAG section.

---

## Decision summary

| Decision | Choice |
|---|---|
| Script | `review_rag.py` (not a flag on `query_rag.py`) |
| Default output | Human text; `--format json` for CI |
| Compare | Dense + BM25 + RRF; rerank only if requested |
| Eval | URL gold list, prefix match, Hit@k + MRR |
| LLM | None |
