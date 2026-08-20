import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from crawler import Crawler, FilesystemSink, Frontier
from crawler.url_list import collect_target_urls, filter_in_scope, load_url_file


def _start_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


class _Handler(BaseHTTPRequestHandler):
    hits: dict[str, int] = {}

    def log_message(self, format, *args):
        del format, args

    def do_GET(self):
        path = urlparse(self.path).path
        _Handler.hits[path] = _Handler.hits.get(path, 0) + 1
        if path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self._ok(body, "text/plain")
            return
        if path == "/":
            self._page("home " * 40, ["/a", "/b"])
            return
        if path == "/a":
            self._page("page a content " * 40, ["/b", "/c"])
            return
        if path in {"/b", "/c"}:
            self._page(f"page {path} " * 40)
            return
        self.send_response(404)
        self.end_headers()

    def _page(self, text: str, links: list[str] | None = None):
        anchors = "".join(f'<a href="{href}">{href}</a>' for href in (links or []))
        html = (
            f"<html><head><title>{text[:16]}</title></head>"
            f"<body><main><p>{text}</p>{anchors}</main></body></html>"
        )
        self._ok(html.encode("utf-8"))

    def _ok(self, body: bytes, content_type: str = "text/html"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site():
    _Handler.hits = {}
    server, base = _start_server(_Handler)
    yield base
    server.shutdown()
    server.server_close()


def test_load_url_file(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text(
        "# comment\nhttps://example.com/a\n\nhttps://example.com/b\n",
        encoding="utf-8",
    )
    assert load_url_file(str(path)) == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    urls = collect_target_urls(urls=["https://example.com/a"], url_file=str(path))
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_filter_out_of_scope():
    accepted, rejected = filter_in_scope(
        ["https://example.com/a", "https://other.com/x"],
        "example.com",
        False,
    )
    assert accepted == ["https://example.com/a"]
    assert rejected == ["https://other.com/x"]


async def test_no_follow_url_list_only(site, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    frontier = Frontier(str(out / "crawl_state.db"))
    sink = FilesystemSink(str(out), "markdown")
    crawler = Crawler(
        site + "/",
        frontier,
        sink,
        max_depth=3,
        max_pages=20,
        concurrency=2,
        delay=0,
        ignore_robots=True,
        extra_urls=[site + "/a"],
        no_follow=True,
    )
    counts = await crawler.run()
    assert counts["done"] == 1
    assert _Handler.hits.get("/a", 0) >= 1
    assert _Handler.hits.get("/", 0) == 0
    assert _Handler.hits.get("/b", 0) == 0
    assert _Handler.hits.get("/c", 0) == 0


async def test_reprocess_url(site, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    frontier = Frontier(str(out / "crawl_state.db"))
    sink = FilesystemSink(str(out), "markdown")
    first = Crawler(
        site + "/",
        frontier,
        sink,
        max_depth=0,
        max_pages=5,
        concurrency=1,
        delay=0,
        ignore_robots=True,
        extra_urls=[site + "/a"],
        no_follow=True,
    )
    await first.run()
    hits_after_first = _Handler.hits.get("/a", 0)
    assert hits_after_first >= 1

    frontier2 = Frontier(str(out / "crawl_state.db"))
    sink2 = FilesystemSink(str(out), "markdown")
    second = Crawler(
        site + "/",
        frontier2,
        sink2,
        max_depth=0,
        max_pages=5,
        concurrency=1,
        delay=0,
        ignore_robots=True,
        no_follow=True,
        reprocess_urls=[site + "/a"],
    )
    counts = await second.run()
    assert counts["done"] >= 1
    assert _Handler.hits.get("/a", 0) > hits_after_first


async def test_sqlite_no_follow(site, tmp_path):
    from crawler import SqliteSink

    db = tmp_path / "crawl.db"
    frontier = Frontier(str(db))
    sink = SqliteSink(str(db), "markdown")
    crawler = Crawler(
        site + "/",
        frontier,
        sink,
        max_depth=2,
        max_pages=20,
        concurrency=2,
        delay=0,
        ignore_robots=True,
        extra_urls=[site + "/a"],
        no_follow=True,
    )
    counts = await crawler.run()
    assert counts["done"] == 1
    import sqlite3

    conn = sqlite3.connect(db)
    urls = {row[0] for row in conn.execute("SELECT url FROM scraped_pages")}
    conn.close()
    assert any(u.endswith("/a") for u in urls)
    assert not any(u.endswith("/b") for u in urls)


async def test_drain_pending_bypasses_small_max_pages(site, tmp_path):
    """With done already high, --drain-pending raises the claim cap so pending runs."""
    out = tmp_path / "out"
    out.mkdir()
    frontier = Frontier(str(out / "crawl_state.db"))
    sink = FilesystemSink(str(out), "markdown")

    # First crawl: leave /a and /b pending by capping at 1 done page
    first = Crawler(
        site + "/",
        frontier,
        sink,
        max_depth=2,
        max_pages=1,
        concurrency=1,
        delay=0,
        ignore_robots=True,
    )
    counts1 = await first.run()
    assert counts1["done"] == 1
    assert counts1["pending"] >= 1

    frontier2 = Frontier(str(out / "crawl_state.db"))
    sink2 = FilesystemSink(str(out), "markdown")
    second = Crawler(
        site + "/",
        frontier2,
        sink2,
        max_depth=2,
        max_pages=1,  # would normally stop immediately
        concurrency=2,
        delay=0,
        ignore_robots=True,
        no_follow=True,
        drain_pending=True,
    )
    counts2 = await second.run()
    assert counts2["pending"] == 0
    assert counts2["done"] > counts1["done"]


def test_drain_max_pages_helper():
    from crawler.status import drain_max_pages

    assert drain_max_pages({"done": 100, "pending": 5, "in_progress": 1}, floor=50) == 106
    assert drain_max_pages({"done": 10, "pending": 0, "in_progress": 0}, floor=500) == 500
