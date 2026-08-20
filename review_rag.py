import argparse
import json
import sys

from rag.config import RagConfig
from rag.review import (
    ReviewSession,
    format_gold_summary,
    format_text_report,
    load_gold,
    metrics_for_queries,
    review_to_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review RAG retrieval (human report, compare channels, gold metrics)"
    )
    parser.add_argument("question", nargs="?", type=str, help="Natural-language query")
    parser.add_argument("--config", type=str, help="Optional rag.yaml")
    parser.add_argument("--persist-dir", type=str, help="Index directory")
    parser.add_argument("--store", choices=["chroma", "qdrant"])
    parser.add_argument("--qdrant-url", type=str)
    parser.add_argument("--embedder", choices=["local", "openai", "hash"])
    parser.add_argument("--embedder-model", type=str)
    parser.add_argument("-k", type=int, help="Hits per channel")
    parser.add_argument("--hybrid", action="store_true", help="Primary channel is RRF")
    parser.add_argument("--rerank", action="store_true", help="Primary channel is rerank")
    parser.add_argument("--filter-url-prefix", type=str)
    parser.add_argument("--compare", action="store_true", help="Show dense / BM25 / RRF side by side")
    parser.add_argument("--gold", type=str, help="JSONL file of {query, expected_urls}")
    parser.add_argument(
        "--expect-url",
        action="append",
        default=[],
        help="Expected URL for a single query (repeatable)",
    )
    parser.add_argument("--snippet-chars", type=int, default=280)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if gold Hit@k is less than 1.0",
    )
    return parser


def _merge(args: argparse.Namespace) -> RagConfig:
    config = RagConfig.from_yaml(args.config) if args.config else RagConfig()
    return config.merge_cli(
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


def main() -> None:
    args = build_parser().parse_args()
    if not args.gold and not args.question:
        print("Pass a question or --gold FILE", file=sys.stderr)
        raise SystemExit(2)
    config = _merge(args)
    session = ReviewSession(config)
    exit_code = 0
    try:
        if args.gold:
            gold_rows = load_gold(args.gold)
            reports = []
            metric_rows = []
            for item in gold_rows:
                review = session.review_query(
                    item["query"],
                    expected_urls=item["expected_urls"],
                    compare=args.compare,
                )
                reports.append(review)
                gold = review.gold or {}
                metric_rows.append(
                    {
                        "query": review.query,
                        "expected_urls": item["expected_urls"],
                        "rank": gold.get("rank"),
                        "found_urls": gold.get("found_urls") or [],
                        "missed_urls": gold.get("missed_urls") or [],
                    }
                )
            metrics = metrics_for_queries(metric_rows)
            if args.format == "json":
                payload = {
                    "metrics": metrics,
                    "reviews": [
                        review_to_json(review, compare=args.compare, snippet_chars=args.snippet_chars)
                        for review in reports
                    ],
                }
                json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
                sys.stdout.write("\n")
            else:
                for review in reports:
                    sys.stdout.write(
                        format_text_report(
                            review, compare=args.compare, snippet_chars=args.snippet_chars
                        )
                    )
                    sys.stdout.write("\n")
                sys.stdout.write(format_gold_summary(metric_rows, metrics))
            if args.strict and metrics["hit_at_k"] < 1.0:
                exit_code = 1
        else:
            review = session.review_query(
                args.question,
                expected_urls=args.expect_url or None,
                compare=args.compare,
            )
            if args.format == "json":
                json.dump(
                    review_to_json(review, compare=args.compare, snippet_chars=args.snippet_chars),
                    sys.stdout,
                    indent=2,
                    ensure_ascii=False,
                )
                sys.stdout.write("\n")
            else:
                sys.stdout.write(
                    format_text_report(
                        review, compare=args.compare, snippet_chars=args.snippet_chars
                    )
                )
            if args.strict and args.expect_url:
                gold = review.gold or {}
                if gold.get("rank") is None:
                    exit_code = 1
    finally:
        session.close()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
