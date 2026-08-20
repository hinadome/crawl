from __future__ import annotations

import os

from rag.chunking import ParentChildChunker, RecursiveMarkdownChunker
from rag.config import RagConfig
from rag.embeddings import HashEmbedder, LocalEmbedder, OpenAIEmbedder
from rag.sources import DiskSource, SqliteSource
from rag.stores.chroma import ChromaStore
from rag.stores.qdrant import QdrantStore
from rag.types import Chunker, Embedder, Source, VectorStore


def build_source(config: RagConfig) -> Source:
    if config.source_type == "disk":
        return DiskSource(config.source_path)
    if config.source_type == "sqlite":
        return SqliteSource(config.source_path)
    raise ValueError(f"Unknown source type {config.source_type}")


def build_chunker(config: RagConfig) -> Chunker:
    if config.chunker == "recursive":
        return RecursiveMarkdownChunker(config.chunk_size, config.chunk_overlap)
    if config.chunker == "parent_child":
        return ParentChildChunker(
            parent_size=config.parent_size,
            child_size=config.child_size,
            overlap=config.chunk_overlap,
        )
    raise ValueError(f"Unknown chunker {config.chunker}")


def build_embedder(config: RagConfig) -> Embedder:
    if config.embedder == "hash":
        return HashEmbedder()
    if config.embedder == "local":
        return LocalEmbedder(config.embedder_model or "BAAI/bge-small-en-v1.5")
    if config.embedder == "openai":
        return OpenAIEmbedder(config.embedder_model or "text-embedding-3-small")
    raise ValueError(f"Unknown embedder {config.embedder}")


def build_store(config: RagConfig, dimensions: int) -> VectorStore:
    persist = os.path.join(config.persist_dir, config.store)
    os.makedirs(config.persist_dir, exist_ok=True)
    if config.store == "chroma":
        return ChromaStore(persist, collection=config.collection)
    if config.store == "qdrant":
        return QdrantStore(
            persist_dir=None if config.qdrant_url else persist,
            url=config.qdrant_url,
            collection=config.collection,
            dimensions=dimensions,
        )
    raise ValueError(f"Unknown store {config.store}")
