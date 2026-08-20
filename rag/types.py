from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


@dataclass
class Document:
    url: str
    title: str
    text: str
    content_hash: str
    source_format: str
    scraped_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    url: str
    title: str
    text: str
    embed_text: str
    index: int
    token_count: int
    heading_path: str | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str


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

    def query(
        self,
        vector: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]: ...
