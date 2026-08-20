from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from rag.catalog import Catalog
from rag.config import RagConfig
from rag.factory import build_embedder, build_store
from rag.pipeline import _channels_open, primary_channel
from rag.types import Hit


def snippet(text: str, limit: int = 280) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def url_matches_gold(hit_url: str, expected: str) -> bool:
    if hit_url == expected:
        return True
    expected = expected.rstrip("/")
    return hit_url.startswith(expected + "/") or hit_url.startswith(expected)


def gold_rank(hits: list[Hit], expected_urls: list[str]) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if any(url_matches_gold(hit.chunk.url, expected) for expected in expected_urls):
            return index
    return None


def found_expected(hits: list[Hit], expected_urls: list[str]) -> list[str]:
    found: list[str] = []
    for expected in expected_urls:
        if any(url_matches_gold(hit.chunk.url, expected) for hit in hits):
            found.append(expected)
    return found


def metrics_for_queries(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"hit_at_k": 0.0, "mrr": 0.0, "recall_at_k": 0.0, "queries": 0}
    hits = 0
    mrr_sum = 0.0
    recall_sum = 0.0
    for row in rows:
        expected = row["expected_urls"]
        rank = row["rank"]
        if rank is not None:
            hits += 1
            mrr_sum += 1.0 / rank
        found = row["found_urls"]
        recall_sum += (len(found) / len(expected)) if expected else 0.0
    n = len(rows)
    return {
        "hit_at_k": hits / n,
        "mrr": mrr_sum / n,
        "recall_at_k": recall_sum / n,
        "queries": n,
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def hit_urls(hits: list[Hit]) -> list[str]:
    seen: list[str] = []
    for hit in hits:
        if hit.chunk.url not in seen:
            seen.append(hit.chunk.url)
    return seen


def load_gold(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            query = item.get("query")
            expected = item.get("expected_urls") or []
            if not query:
                continue
            rows.append({"query": query, "expected_urls": list(expected)})
    return rows


@dataclass
class QueryReview:
    query: str
    stats: dict[str, Any]
    primary: str
    channels: dict[str, list[Hit]]
    overlap: dict[str, Any] = field(default_factory=dict)
    gold: dict[str, Any] | None = None


class ReviewSession:
    def __init__(self, config: RagConfig):
        self.config = config
        self.embedder = build_embedder(config)
        catalog_path = os.path.join(config.persist_dir, "catalog.db")
        if not os.path.exists(catalog_path):
            raise FileNotFoundError(f"No catalog at {catalog_path}; ingest first")
        self.catalog = Catalog(catalog_path)
        self.store = build_store(config, self.embedder.dimensions)

    def close(self) -> None:
        close = getattr(self.store, "close", None)
        if close:
            close()
        self.catalog.close()

    def review_query(
        self,
        question: str,
        *,
        expected_urls: list[str] | None = None,
        compare: bool = False,
    ) -> QueryReview:
        channels = _channels_open(
            self.config, question, self.catalog, self.store, self.embedder
        )
        primary = primary_channel(self.config)
        if primary not in channels:
            primary = "dense"
        stats = self.catalog.stats()
        stats.update(
            {
                "persist_dir": self.config.persist_dir,
                "store": self.config.store,
                "embedder": self.config.embedder,
            }
        )
        overlap: dict[str, Any] = {}
        if compare:
            dense_urls = set(hit_urls(channels.get("dense", [])))
            bm25_urls = set(hit_urls(channels.get("bm25", [])))
            rrf_urls = set(hit_urls(channels.get("rrf", [])))
            overlap = {
                "jaccard_dense_bm25": jaccard(dense_urls, bm25_urls),
                "jaccard_dense_rrf": jaccard(dense_urls, rrf_urls),
                "bm25_not_in_dense": sorted(bm25_urls - dense_urls),
                "dense_not_in_bm25": sorted(dense_urls - bm25_urls),
            }
        gold = None
        if expected_urls:
            hits = channels[primary]
            rank = gold_rank(hits, expected_urls)
            found = found_expected(hits, expected_urls)
            missed = [url for url in expected_urls if url not in found]
            gold = {
                "expected_urls": expected_urls,
                "rank": rank,
                "found_urls": found,
                "missed_urls": missed,
            }
        return QueryReview(
            query=question,
            stats=stats,
            primary=primary,
            channels=channels,
            overlap=overlap,
            gold=gold,
        )


def hits_payload(hits: list[Hit], snippet_chars: int) -> list[dict[str, Any]]:
    rows = []
    for rank, hit in enumerate(hits, start=1):
        rows.append(
            {
                "rank": rank,
                "score": hit.score,
                "source": hit.source,
                "title": hit.chunk.title,
                "url": hit.chunk.url,
                "heading_path": hit.chunk.heading_path,
                "chunk_id": hit.chunk.chunk_id,
                "snippet": snippet(hit.chunk.text, snippet_chars),
            }
        )
    return rows


def review_to_json(review: QueryReview, *, compare: bool, snippet_chars: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": review.stats,
        "query": review.query,
        "primary": review.primary,
        "hits": hits_payload(review.channels.get(review.primary, []), snippet_chars),
    }
    if compare:
        payload["channels"] = {
            name: hits_payload(hits, snippet_chars) for name, hits in review.channels.items()
        }
        payload["overlap"] = review.overlap
    if review.gold:
        payload["gold"] = review.gold
    return payload


def format_hit_block(rank: int, hit: Hit, snippet_chars: int) -> str:
    heading = f"\n   heading: {hit.chunk.heading_path}" if hit.chunk.heading_path else ""
    return (
        f"{rank:<2} {hit.score:6.3f}  {hit.source:<6}  {hit.chunk.title[:28]:<28}  {hit.chunk.url}\n"
        f"{heading}"
        f"   snippet: {snippet(hit.chunk.text, snippet_chars)}"
    ).replace("\n\n", "\n")


def format_text_report(
    review: QueryReview,
    *,
    compare: bool,
    snippet_chars: int,
) -> str:
    stats = review.stats
    lines = [
        f"Index: {stats.get('persist_dir')}  store={stats.get('store')}  "
        f"embedder={stats.get('embedder')}  docs={stats.get('docs')}  chunks={stats.get('chunks')}",
        f"Query: {review.query}",
        f"Primary: {review.primary}",
        "",
        "#  score   src    title                         url",
    ]
    hits = review.channels.get(review.primary, [])
    if not hits:
        lines.append("(no hits)")
    for rank, hit in enumerate(hits, start=1):
        lines.append(format_hit_block(rank, hit, snippet_chars))
        lines.append("")
    if compare:
        lines.append("Compare (top URLs by channel)")
        for name, channel_hits in review.channels.items():
            urls = ", ".join(hit_urls(channel_hits)[:8]) or "(none)"
            lines.append(f"  {name}: {urls}")
        overlap = review.overlap
        lines.append(
            f"  jaccard dense∩bm25={overlap.get('jaccard_dense_bm25', 0):.2f}  "
            f"dense∩rrf={overlap.get('jaccard_dense_rrf', 0):.2f}"
        )
        missed = overlap.get("bm25_not_in_dense") or []
        if missed:
            lines.append("  BM25 found, dense missed:")
            for url in missed:
                lines.append(f"    - {url}")
        lines.append("")
    if review.gold:
        gold = review.gold
        lines.append(
            f"Gold: rank={gold['rank']}  found={gold['found_urls']}  missed={gold['missed_urls']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def format_gold_summary(per_query: list[dict[str, Any]], metrics: dict[str, float]) -> str:
    lines = [
        f"Gold summary  queries={metrics['queries']}  "
        f"Hit@k={metrics['hit_at_k']:.3f}  MRR={metrics['mrr']:.3f}  "
        f"Recall@k={metrics['recall_at_k']:.3f}",
        "",
    ]
    for row in per_query:
        lines.append(
            f"- {row['query']!r}  rank={row['rank']}  missed={row['missed_urls']}"
        )
    return "\n".join(lines) + "\n"
