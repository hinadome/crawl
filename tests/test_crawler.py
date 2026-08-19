from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from crawler import Crawler, FilesystemSink, Frontier


class _SiteState:
    def __init__(self):
        self.hits: dict[str, int] = {}
        self.lock = threading.Lock()


def _start_server(handler_cls) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def _make_handler(state: _SiteState, slow_path: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            del format, args

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            with state.lock:
                state.hits[path] = state.hits.get(path, 0) + 1
                hit = state.hits[path]

            if path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /secret\n"
                self._ok(body, "text/plain")
                return
            if slow_path and path == slow_path:
                import time

                time.sleep(2)
                self._ok(b"<html><body><main><p>slow page text here</p></main></body></html>")
                return
            if path == "/flaky":
                if hit == 1:
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"slow down")
                    return
                self._page("flaky ok", extra_links=[])
                return
            if path == "/secret":
                self._page("should not crawl")
                return
            if path == "/":
                extra = ["/a", "/b", "/secret", "/author"]
                if slow_path:
                    extra.append(slow_path)
                self._page("home " * 40, extra_links=extra)
                return
            if path in {"/a", "/b", "/author"}:
                self._page(f"{path} content " * 40)
                return
            self.send_response(404)
            self.end_headers()

        def _page(self, text: str, extra_links: list[str] | None = None):
            links = extra_links or []
            anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
            html = (
                f"<html><head><title>{text[:20]}</title></head>"
                f"<body><main><p>{text}</p>{anchors}</main></body></html>"
            )
            self._ok(html.encode("utf-8"))

        def _ok(self, body: bytes, content_type: str = "text/html"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@pytest.fixture
def http_site():
    state = _SiteState()
    server, base = _start_server(_make_handler(state))
    yield base, state
    server.shutdown()
    server.server_close()


async def _run(tmp_path, start_url, **kwargs):
    out = tmp_path / "out"
    out.mkdir()
    frontier = Frontier(str(out / "crawl_state.db"))
    sink = FilesystemSink(str(out), "markdown")
    crawler = Crawler(
        start_url,
        frontier,
        sink,
        max_depth=kwargs.get("max_depth", 2),
        max_pages=kwargs.get("max_pages", 50),
        concurrency=kwargs.get("concurrency", 3),
        delay=0,
        ignore_robots=kwargs.get("ignore_robots", False),
        fetch_timeout=kwargs.get("fetch_timeout", 35.0),
        max_attempts=kwargs.get("max_attempts", 3),
    )
    return await crawler.run()


async def test_workers_and_max_pages(http_site, tmp_path):
    base, _state = http_site
    counts = await _run(tmp_path, base + "/", max_pages=2, concurrency=3)
    assert counts["done"] == 2


async def test_robots_and_author_not_filtered(http_site, tmp_path):
    base, _state = http_site
    counts = await _run(tmp_path, base + "/", max_pages=20, concurrency=2)
    assert counts["done"] >= 4
    assert counts["skipped"] >= 1

    import sqlite3

    db = sqlite3.connect(tmp_path / "out" / "crawl_state.db")
    urls = {row[0] for row in db.execute("SELECT url FROM crawl_state WHERE status = 'done'")}
    skipped = {
        row[0] for row in db.execute("SELECT url FROM crawl_state WHERE status = 'skipped'")
    }
    assert any(u.endswith("/author") for u in urls)
    assert any("/secret" in u for u in skipped)


async def test_timeout_isolates_one_url(tmp_path):
    state = _SiteState()
    server, base = _start_server(_make_handler(state, slow_path="/slow"))
    try:
        counts = await _run(
            tmp_path,
            base + "/",
            max_pages=10,
            concurrency=3,
            ignore_robots=True,
            fetch_timeout=0.3,
            max_attempts=1,
        )
        assert counts["done"] >= 3
        assert counts["failed"] >= 1
    finally:
        server.shutdown()
        server.server_close()


async def test_retry_on_429(http_site, tmp_path):
    base, state = http_site
    counts = await _run(
        tmp_path,
        base + "/flaky",
        max_depth=0,
        max_pages=5,
        concurrency=1,
        ignore_robots=True,
    )
    assert counts["done"] == 1
    assert state.hits.get("/flaky", 0) >= 2
