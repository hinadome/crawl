from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class RagConfig:
    source_type: str = "disk"
    source_path: str = "scraped_output"
    chunker: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    parent_size: int = 1024
    child_size: int = 160
    embedder: str = "local"
    embedder_model: str | None = None
    store: str = "chroma"
    persist_dir: str = "rag_index"
    qdrant_url: str | None = None
    collection: str = "chunks"
    k: int = 8
    hybrid: bool = False
    rerank: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"
    fetch_k: int = 20
    force_reindex: bool = False
    prune: bool = False
    debug: bool = False
    filter_url_prefix: str | None = None

    @classmethod
    def from_yaml(cls, path: str) -> "RagConfig":
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        source = raw.get("source") or {}
        chunker = raw.get("chunker") or {}
        embedder = raw.get("embedder") or {}
        store = raw.get("store") or {}
        retrieve = raw.get("retrieve") or {}
        return cls(
            source_type=source.get("type", "disk"),
            source_path=source.get("path", "scraped_output"),
            chunker=chunker.get("type", "recursive"),
            chunk_size=int(chunker.get("tokens", 512)),
            chunk_overlap=int(chunker.get("overlap", 64)),
            parent_size=int(chunker.get("parent_tokens", 1024)),
            child_size=int(chunker.get("child_tokens", 160)),
            embedder=embedder.get("type", "local"),
            embedder_model=embedder.get("model"),
            store=store.get("type", "chroma"),
            persist_dir=store.get("persist_dir", "rag_index"),
            qdrant_url=store.get("qdrant_url"),
            collection=store.get("collection", "chunks"),
            k=int(retrieve.get("k", 8)),
            hybrid=bool(retrieve.get("hybrid", False)),
            rerank=bool(retrieve.get("rerank", False)),
            rerank_model=retrieve.get("rerank_model", "BAAI/bge-reranker-base"),
            fetch_k=int(retrieve.get("fetch_k", 20)),
        )

    def merge_cli(self, **overrides: Any) -> "RagConfig":
        data = self.__dict__.copy()
        for key, value in overrides.items():
            if value is not None:
                data[key] = value
        return RagConfig(**data)
