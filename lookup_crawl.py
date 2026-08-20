#!/usr/bin/env python3
"""Look up where a crawled URL is stored on disk."""

from __future__ import annotations

import argparse
import json
import sys

from crawler.lookup import format_disk_lookup, lookup_disk_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate disk location for a crawled URL (crawl_state.db / hash path)"
    )
    parser.add_argument("url", type=str, help="Page URL to look up")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="scraped_output",
        help="Disk crawl output directory (default: scraped_output)",
    )
    parser.add_argument(
        "-t",
        "--output-type",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Extension used when computing expected path (default: markdown)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 unless status=done and the file exists on disk",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    loc = lookup_disk_url(args.output_dir, args.url, output_type=args.output_type)
    if args.format == "json":
        json.dump(loc.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_disk_lookup(loc))
    if args.strict and not loc.ok:
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
