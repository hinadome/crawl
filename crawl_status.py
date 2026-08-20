#!/usr/bin/env python3
"""Show crawl frontier queue counts (pending / done / …)."""

from __future__ import annotations

import argparse
import json
import sys

from crawler.status import format_frontier_status, frontier_status, resolve_frontier_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show pending/done/failed counts for a crawl frontier"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="Disk crawl output dir (reads <dir>/crawl_state.db)",
    )
    parser.add_argument(
        "-f",
        "--db",
        type=str,
        default=None,
        help="Frontier SQLite path (SQLite crawl DB, or crawl_state.db directly)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.output_dir and not args.db:
        args.output_dir = "scraped_output"
    try:
        db_path = resolve_frontier_db(output_dir=args.output_dir, db_path=args.db)
        status = frontier_status(db_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.format == "json":
        json.dump(status.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_frontier_status(status))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
