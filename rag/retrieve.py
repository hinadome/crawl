from __future__ import annotations

from collections import defaultdict

from rank_bm25 import BM25Okapi

from rag.catalog import Catalog
from rag.types import Chunk, Hit


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def tokenize(text: str) -> list[str]:
    return [token for token in text.lower().replace("/", " ").split() if token]


class HybridRetriever:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._bm25: BM25Okapi | None = None
        self._ids: list[str] = []

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        chunks = self.catalog.indexed_chunks()
        self._ids = [chunk.chunk_id for chunk in chunks]
        corpus = [tokenize(chunk.text) for chunk in chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else BM25Okapi([["empty"]])

    def invalidate(self) -> None:
        self._bm25 = None
        self._ids = []

    def bm25_rank(self, query: str, k: int) -> list[str]:
        return [chunk_id for chunk_id, _score in self.bm25_rank_scored(query, k)]

    def bm25_rank_scored(self, query: str, k: int) -> list[tuple[str, float]]:
        self._ensure_bm25()
        if not self._ids or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self._ids, scores), key=lambda item: item[1], reverse=True)
        return [(chunk_id, float(score)) for chunk_id, score in ranked[:k] if score > 0]


def hydrate(catalog: Catalog, ranked: list[tuple[str, float]], source: str) -> list[Hit]:
    hits: list[Hit] = []
    for chunk_id, score in ranked:
        chunk = catalog.chunk(chunk_id)
        if chunk is None:
            continue
        if chunk.parent_id:
            parent = catalog.parent(chunk.parent_id)
            if parent is not None:
                chunk = Chunk(
                    chunk_id=chunk.chunk_id,
                    url=chunk.url,
                    title=chunk.title,
                    text=parent.text,
                    embed_text=parent.embed_text,
                    index=chunk.index,
                    token_count=parent.token_count,
                    heading_path=chunk.heading_path or parent.heading_path,
                    parent_id=chunk.parent_id,
                    metadata=chunk.metadata,
                )
        hits.append(Hit(chunk=chunk, score=float(score), source=source))
    return hits


def apply_url_prefix(hits: list[Hit], prefix: str | None) -> list[Hit]:
    if not prefix:
        return hits
    return [hit for hit in hits if hit.chunk.url.startswith(prefix)]


class CrossEncoderReranker:
    def __init__(self, model: str = "BAAI/bge-reranker-base"):
        self.model_id = model
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_id)
        return self._model

    def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        if not hits:
            return []
        model = self._load()
        pairs = [(query, hit.chunk.text) for hit in hits]
        scores = model.predict(pairs)
        rescored = [
            Hit(chunk=hit.chunk, score=float(score), source="rerank")
            for hit, score in zip(hits, scores)
        ]
        rescored.sort(key=lambda hit: hit.score, reverse=True)
        return rescored[:top_n]
