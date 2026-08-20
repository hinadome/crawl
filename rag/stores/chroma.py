from __future__ import annotations

from typing import Any

import chromadb

from rag.stores.common import _meta
from rag.types import Chunk


class ChromaStore:
    def __init__(self, persist_dir: str, collection: str = "chunks"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=vectors,
            documents=[chunk.embed_text for chunk in chunks],
            metadatas=[_meta(chunk) for chunk in chunks],
        )

    def delete_by_url(self, url: str) -> None:
        self._collection.delete(where={"url": url})

    def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        count = self._collection.count()
        if count == 0:
            return []
        n_results = min(max(k, 1), count)
        kwargs: dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": n_results,
            "include": ["distances"],
        }
        if where:
            kwargs["where"] = where
        result = self._collection.query(**kwargs)
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[tuple[str, float]] = []
        for chunk_id, distance in zip(ids, distances):
            score = 1.0 - float(distance)
            hits.append((chunk_id, score))
        return hits[:k]

    def close(self) -> None:
        pass
