from __future__ import annotations

import os
import sys
from rag.catalog import Catalog
from rag.chunking.parent_child import ParentChildChunker
from rag.config import RagConfig
from rag.factory import build_chunker, build_embedder, build_source, build_store
from rag.retrieve import CrossEncoderReranker, HybridRetriever, apply_url_prefix, hydrate, rrf_fuse
from rag.types import Chunk, Hit


class IngestStats:
    def __init__(self):
        self.seen = 0
        self.skipped = 0
        self.indexed = 0
        self.deleted = 0
        self.chunks = 0

    def as_dict(self) -> dict:
        return {
            "seen": self.seen,
            "skipped": self.skipped,
            "indexed": self.indexed,
            "deleted": self.deleted,
            "chunks": self.chunks,
        }


def _debug(config: RagConfig, message: str) -> None:
    if config.debug:
        print(f"[ingest] {message}", file=sys.stderr, flush=True)


def ingest(config: RagConfig) -> dict:
    source = build_source(config)
    chunker = build_chunker(config)
    embedder = build_embedder(config)
    os.makedirs(config.persist_dir, exist_ok=True)
    catalog = Catalog(os.path.join(config.persist_dir, "catalog.db"))
    store = build_store(config, embedder.dimensions)
    stats = IngestStats()
    seen_urls: set[str] = set()
    store_path = os.path.join(config.persist_dir, config.store)
    if config.store == "qdrant" and config.qdrant_url:
        store_location = config.qdrant_url
    else:
        store_location = store_path
    _debug(
        config,
        f"start source={config.source_type}:{config.source_path} "
        f"store={config.store} location={store_location} "
        f"persist_dir={config.persist_dir} "
        f"chunker={chunker.name} embedder={embedder.model_id}",
    )
    try:
        for document in source.iter_documents():
            stats.seen += 1
            seen_urls.add(document.url)
            existing = catalog.get_document(document.url)
            same = (
                existing is not None
                and existing["content_hash"] == document.content_hash
                and existing["chunker"] == chunker.name
                and existing["embedder"] == embedder.model_id
                and existing["store"] == config.store
            )
            if same and not config.force_reindex:
                stats.skipped += 1
                _debug(
                    config,
                    f"SKIP  #{stats.seen} {document.url} "
                    f"(indexed={stats.indexed} skipped={stats.skipped})",
                )
                continue
            reason = "new"
            if existing is not None:
                if config.force_reindex:
                    reason = "force-reindex"
                elif existing["content_hash"] != document.content_hash:
                    reason = "content-changed"
                elif existing["store"] != config.store:
                    reason = f"store-changed:{existing['store'] or 'unknown'}->{config.store}"
                else:
                    reason = "settings-changed"
            _debug(config, f"INDEX #{stats.seen} {document.url} ({reason})")
            store.delete_by_url(document.url)
            chunks = chunker.split(document)
            parents: list[Chunk] = []
            if isinstance(chunker, ParentChildChunker):
                parents = list(chunker._parents.values())
            vectors = embedder.embed_documents([chunk.embed_text for chunk in chunks])
            store.upsert(chunks, vectors)
            catalog.replace_document(
                document.url,
                document.content_hash,
                chunker.name,
                embedder.model_id,
                config.store,
                document.scraped_at,
                chunks,
                parents,
            )
            stats.indexed += 1
            stats.chunks += len(chunks)
            _debug(
                config,
                f"DONE  #{stats.seen} {document.url} "
                f"chunks={len(chunks)} "
                f"(indexed={stats.indexed} skipped={stats.skipped} total_chunks={stats.chunks})",
            )
        if config.prune:
            for url in catalog.all_urls() - seen_urls:
                _debug(config, f"PRUNE {url}")
                store.delete_by_url(url)
                catalog.delete_url(url)
                stats.deleted += 1
        _debug(
            config,
            f"finish seen={stats.seen} indexed={stats.indexed} "
            f"skipped={stats.skipped} deleted={stats.deleted} chunks={stats.chunks}",
        )
    finally:
        close = getattr(store, "close", None)
        if close:
            close()
        catalog.close()
    return stats.as_dict()


def _channels_open(
    config: RagConfig,
    question: str,
    catalog: Catalog,
    store,
    embedder,
) -> dict[str, list[Hit]]:
    fetch_k = max(config.k, config.fetch_k)
    vector = embedder.embed_query(question)
    dense_ranked = store.query(vector, fetch_k)
    hybrid = HybridRetriever(catalog)
    bm25_ranked = hybrid.bm25_rank_scored(question, fetch_k)
    fused = rrf_fuse(
        [
            [chunk_id for chunk_id, _score in dense_ranked],
            [chunk_id for chunk_id, _score in bm25_ranked],
        ]
    )
    prefix = config.filter_url_prefix
    dense = apply_url_prefix(hydrate(catalog, dense_ranked, "dense"), prefix)[: config.k]
    bm25 = apply_url_prefix(hydrate(catalog, bm25_ranked, "bm25"), prefix)[: config.k]
    rrf = apply_url_prefix(hydrate(catalog, fused[:fetch_k], "rrf"), prefix)[: config.k]
    channels: dict[str, list[Hit]] = {"dense": dense, "bm25": bm25, "rrf": rrf}
    if config.rerank:
        pool = rrf if rrf else dense
        reranker = CrossEncoderReranker(config.rerank_model)
        channels["rerank"] = reranker.rerank(question, pool[:fetch_k], config.k)
    return channels


def primary_channel(config: RagConfig) -> str:
    if config.rerank:
        return "rerank"
    if config.hybrid:
        return "rrf"
    return "dense"


def query_channels(config: RagConfig, question: str) -> dict[str, list[Hit]]:
    embedder = build_embedder(config)
    catalog = Catalog(os.path.join(config.persist_dir, "catalog.db"))
    store = build_store(config, embedder.dimensions)
    try:
        return _channels_open(config, question, catalog, store, embedder)
    finally:
        close = getattr(store, "close", None)
        if close:
            close()
        catalog.close()


def query(config: RagConfig, question: str) -> list[Hit]:
    channels = query_channels(config, question)
    name = primary_channel(config)
    if name not in channels:
        name = "dense"
    return channels[name][: config.k]


def hits_to_json(question: str, hits: list[Hit]) -> dict:
    return {
        "query": question,
        "hits": [
            {
                "text": hit.chunk.text,
                "url": hit.chunk.url,
                "title": hit.chunk.title,
                "score": hit.score,
                "heading_path": hit.chunk.heading_path,
                "chunk_id": hit.chunk.chunk_id,
                "source": hit.source,
            }
            for hit in hits
        ],
    }
