#!/usr/bin/env python3
"""Look up a crawled URL (disk or SQLite) and optionally list links in its content."""

from __future__ import annotations

import argparse
import json
import sys

from crawler.lookup import (
    format_db_lookup,
    format_disk_lookup,
    lookup_db_url,
    lookup_disk_url,
)
from crawler.page_links import (
    format_page_links,
    list_links_from_db_url,
    list_links_from_disk_url,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate location for a crawled URL (disk -o or SQLite -f), "
            "or list URLs linked from its saved content (--links)"
        )
    )
    parser.add_argument("url", type=str, help="Page URL to look up")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="Disk crawl output directory (reads files + crawl_state.db)",
    )
    parser.add_argument(
        "-f",
        "--db",
        type=str,
        default=None,
        help="SQLite crawl database (frontier + scraped_pages)",
    )
    parser.add_argument(
        "-t",
        "--output-type",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Extension used when computing expected disk path (default: markdown)",
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
        help="Exit 1 unless the page is done and content is present",
    )
    parser.add_argument(
        "--links",
        action="store_true",
        help="Parse the saved page content and list all linked URLs",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.output_dir and args.db:
        print("Use either -o/--output-dir or -f/--db, not both", file=sys.stderr)
        raise SystemExit(2)
    if not args.output_dir and not args.db:
        args.output_dir = "scraped_output"

    if args.db:
        if args.links:
            result = list_links_from_db_url(args.db, args.url)
            if args.format == "json":
                json.dump(result.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
                sys.stdout.write("\n")
            else:
                sys.stdout.write(format_page_links(result, include_location=True))
            if args.strict and (not result.location.ok or result.source is None):
                raise SystemExit(1)
            raise SystemExit(0)

        loc = lookup_db_url(args.db, args.url)
        if args.format == "json":
            json.dump(loc.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_db_lookup(loc))
        if args.strict and not loc.ok:
            raise SystemExit(1)
        raise SystemExit(0)

    # Disk store
    if args.links:
        result = list_links_from_disk_url(
            args.output_dir, args.url, output_type=args.output_type
        )
        if args.format == "json":
            json.dump(result.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_page_links(result, include_location=True))
        if args.strict and (not result.location.ok or result.source is None):
            raise SystemExit(1)
        raise SystemExit(0)

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
