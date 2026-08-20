import argparse
import asyncio
import os
import sys

from crawler import Crawler, CrawlAborted, FilesystemSink, Frontier
from crawler.cli_urls import add_url_target_args, url_target_kwargs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resumable disk domain crawler")
    parser.add_argument("start_url", type=str, help="The starting URL for crawling")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="scraped_output",
        help="Directory to store files and crawl_state.db",
    )
    parser.add_argument(
        "-t",
        "--output-type",
        type=str,
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Output file format",
    )
    parser.add_argument("-d", "--max-depth", type=int, default=3, help="Maximum crawl depth")
    parser.add_argument("-p", "--max-pages", type=int, default=500, help="Maximum pages to store")
    parser.add_argument("-c", "--concurrency", type=int, default=2, help="Number of worker tasks")
    parser.add_argument(
        "--include-subdomains",
        action="store_true",
        help="Also crawl hosts that are subdomains of the seed host",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Per-host delay between requests")
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Do not honor robots.txt",
    )
    parser.add_argument(
        "--force-new",
        action="store_true",
        help="Wipe existing crawl state in this output dir and start over",
    )
    parser.add_argument(
        "--sitemap",
        action="store_true",
        help="Seed the frontier from /sitemap.xml",
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Use a browser-like UA and hide webdriver (Playwright fallback only)",
    )
    parser.add_argument(
        "--content",
        choices=["main", "full", "selector"],
        default="main",
        help="How to extract saved body text (default: main content, not nav/chrome)",
    )
    parser.add_argument(
        "--content-selector",
        type=str,
        help="CSS selector when --content selector (e.g. 'main, article, .markdown-body')",
    )
    add_url_target_args(parser)
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.content == "selector" and not args.content_selector:
        print("--content selector requires --content-selector CSS", file=sys.stderr)
        return 2
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    frontier = Frontier(os.path.join(output_dir, "crawl_state.db"))
    sink = FilesystemSink(
        output_dir,
        args.output_type,
        content_mode=args.content,
        content_selector=args.content_selector,
    )
    crawler = Crawler(
        args.start_url,
        frontier,
        sink,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
        delay=args.delay,
        include_subdomains=args.include_subdomains,
        ignore_robots=args.ignore_robots,
        force_new=args.force_new,
        use_sitemap=args.sitemap,
        stealth=args.stealth,
        **url_target_kwargs(args),
    )
    try:
        await crawler.run()
    except CrawlAborted as exc:
        print(f"[ABORT] {exc}", file=sys.stderr)
        return 2
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
