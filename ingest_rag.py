import argparse
import json
import sys

from rag.config import RagConfig
from rag.pipeline import ingest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest crawl output into a RAG index")
    parser.add_argument("--config", type=str, help="Optional rag.yaml")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-disk", dest="from_disk", type=str, help="Crawl output directory")
    source.add_argument("--from-sqlite", dest="from_sqlite", type=str, help="crawl_data.db path")
    parser.add_argument("--store", choices=["chroma", "qdrant"], help="Vector store")
    parser.add_argument("--persist-dir", type=str, help="Index directory")
    parser.add_argument("--qdrant-url", type=str, help="Qdrant HTTP URL (otherwise local path)")
    parser.add_argument("--chunker", choices=["recursive", "parent_child"])
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--chunk-overlap", type=int)
    parser.add_argument("--embedder", choices=["local", "openai", "hash"])
    parser.add_argument("--embedder-model", type=str)
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--prune", action="store_true", help="Delete indexed URLs missing from the source")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print per-URL progress to stderr (skip/index/prune counts)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RagConfig.from_yaml(args.config) if args.config else RagConfig()
    source_type = None
    source_path = None
    if args.from_disk:
        source_type = "disk"
        source_path = args.from_disk
    elif args.from_sqlite:
        source_type = "sqlite"
        source_path = args.from_sqlite
    config = config.merge_cli(
        source_type=source_type,
        source_path=source_path,
        store=args.store,
        persist_dir=args.persist_dir,
        qdrant_url=args.qdrant_url,
        chunker=args.chunker,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embedder=args.embedder,
        embedder_model=args.embedder_model,
        force_reindex=True if args.force_reindex else None,
        prune=True if args.prune else None,
        debug=True if args.debug else None,
    )
    if config.source_type == "disk" and not args.from_disk and not args.config:
        print("Pass --from-disk DIR or --from-sqlite FILE (or --config rag.yaml)", file=sys.stderr)
        raise SystemExit(2)
    stats = ingest(config)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
