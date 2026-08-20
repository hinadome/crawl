from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from rag.stores.common import _meta, _point_id
from rag.types import Chunk


class QdrantStore:
    def __init__(
        self,
        persist_dir: str | None = None,
        url: str | None = None,
        collection: str = "chunks",
        dimensions: int = 384,
    ):
        if url:
            self._client = QdrantClient(url=url)
        elif persist_dir:
            self._client = QdrantClient(path=persist_dir)
        else:
            self._client = QdrantClient(":memory:")
        self.collection = collection
        self.dimensions = dimensions
        self._remote = bool(url)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = {item.name for item in self._client.get_collections().collections}
        if self.collection in names:
            return
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(
                size=self.dimensions,
                distance=qmodels.Distance.COSINE,
            ),
        )
        if self._remote:
            self._client.create_payload_index(
                collection_name=self.collection,
                field_name="url",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        points = []
        for chunk, vector in zip(chunks, vectors):
            points.append(
                qmodels.PointStruct(
                    id=_point_id(chunk.chunk_id),
                    vector=vector,
                    payload=_meta(chunk) | {"chunk_id": chunk.chunk_id},
                )
            )
        self._client.upsert(collection_name=self.collection, points=points)

    def delete_by_url(self, url: str) -> None:
        self._client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="url", match=qmodels.MatchValue(value=url))]
                )
            ),
        )

    def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        query_filter = None
        if where and "url" in where:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="url",
                        match=qmodels.MatchValue(value=where["url"]),
                    )
                ]
            )
        results = self._client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=max(k, 1),
            query_filter=query_filter,
            with_payload=True,
        )
        hits: list[tuple[str, float]] = []
        for point in results.points:
            payload = point.payload or {}
            chunk_id = str(payload.get("chunk_id") or point.id)
            hits.append((chunk_id, float(point.score)))
        return hits

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            close()
