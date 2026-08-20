import argparse
import json
import sys

from rag.config import RagConfig
from rag.pipeline import hits_to_json, query


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query a RAG index (JSON hits for agents)")
    parser.add_argument("question", type=str, help="Natural-language query")
    parser.add_argument("--config", type=str, help="Optional rag.yaml")
    parser.add_argument("--persist-dir", type=str, help="Index directory")
    parser.add_argument("--store", choices=["chroma", "qdrant"])
    parser.add_argument("--qdrant-url", type=str)
    parser.add_argument("--embedder", choices=["local", "openai", "hash"])
    parser.add_argument("--embedder-model", type=str)
    parser.add_argument("-k", type=int, help="Number of hits")
    parser.add_argument("--hybrid", action="store_true", help="Dense + BM25 with RRF")
    parser.add_argument("--rerank", action="store_true", help="Cross-encoder rerank")
    parser.add_argument("--filter-url-prefix", type=str)
    parser.add_argument("--format", choices=["json"], default="json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RagConfig.from_yaml(args.config) if args.config else RagConfig()
    config = config.merge_cli(
        persist_dir=args.persist_dir,
        store=args.store,
        qdrant_url=args.qdrant_url,
        embedder=args.embedder,
        embedder_model=args.embedder_model,
        k=args.k,
        hybrid=True if args.hybrid else None,
        rerank=True if args.rerank else None,
        filter_url_prefix=args.filter_url_prefix,
    )
    hits = query(config, args.question)
    payload = hits_to_json(args.question, hits)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
