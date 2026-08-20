# Retrieval review — task list

Separate `review_rag.py` for humans/CI. `query_rag.py` stays the agent JSON API.

## Slice 1 — channels + single-query report

- [x] Add `Catalog.stats()` (doc count, indexed chunk count, chunker/embedder labels).
- [x] Add BM25 scores (`bm25_rank_scored`) and `query_channels()` (embed query once → dense, BM25, RRF).
- [x] Refactor `pipeline.query` to pick the primary channel from `query_channels` (behavior unchanged for agents).
- [x] `rag/review.py`: text + JSON reports with rank, score, src, title, URL, heading, snippet, index stats.
- [x] `review_rag.py` CLI: question, shared query flags, `--snippet-chars`, `--format text|json`.

## Slice 2 — compare

- [x] `--compare`: print dense / BM25 / RRF (and rerank if `--rerank`).
- [x] Jaccard overlap of top-k URLs; list URLs BM25 found that dense missed.

## Slice 3 — gold metrics

- [x] `--expect-url` (repeatable) for one query.
- [x] `--gold` JSONL `{query, expected_urls}`; prefix match on URLs.
- [x] Hit@k, MRR, Recall@k; per-query missed URLs.
- [x] `--strict`: exit 1 if Hit@k < 1.0.

## Slice 4 — tests and docs

- [x] Compare JSON includes `dense` and `bm25`.
- [x] Gold hit → Hit@k = 1; miss → Hit@k = 0.
- [x] Text report contains URL and snippet.
- [x] README section “Review retrieval”.
- [x] Mark `REVIEW_RAG_IMPLEMENTATION_PLAN.md` as implemented.
