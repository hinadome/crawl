"""Shared crawl CLI flags for URL targeting."""

from __future__ import annotations

import argparse

from crawler.url_list import collect_target_urls


def add_url_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Extra URL to crawl at depth 0 (repeatable)",
    )
    parser.add_argument(
        "--url-file",
        type=str,
        help="File of URLs to crawl (one per line; # comments allowed)",
    )
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="Do not enqueue links discovered on fetched pages",
    )
    parser.add_argument(
        "--reprocess-url",
        action="append",
        default=[],
        dest="reprocess_url",
        help="Force URL back to pending and fetch again (repeatable)",
    )
    parser.add_argument(
        "--drain-pending",
        action="store_true",
        help=(
            "Raise --max-pages so every currently pending URL can be claimed "
            "(after --url / --reprocess-url). Prefer with --no-follow on large resumes."
        ),
    )


def url_target_kwargs(args: argparse.Namespace) -> dict:
    extra = collect_target_urls(urls=args.url, url_file=args.url_file)
    reprocess = collect_target_urls(urls=args.reprocess_url or [])
    return {
        "extra_urls": extra,
        "no_follow": bool(args.no_follow),
        "reprocess_urls": reprocess,
        "drain_pending": bool(getattr(args, "drain_pending", False)),
    }
