from __future__ import annotations

import asyncio
from typing import Protocol
from urllib.parse import urlparse

from crawler.extract import extract_hrefs
from crawler.fetch import BOT_USER_AGENT, FetchResult, Fetcher
from crawler.frontier import ClaimedUrl, Frontier
from crawler.normalize import normalize_url, should_enqueue
from crawler.politeness import Politeness, fetch_sitemap_urls
from crawler.url_list import filter_in_scope

MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 503}
WAF_TITLE_MARKERS = ("Access Denied", "Security Check")


class Sink(Protocol):
    async def save(self, url: str, title: str, html: str) -> str | None: ...

    async def close(self, frontier: Frontier) -> None: ...


class CrawlAborted(Exception):
    """Raised when the DB already belongs to a different seed URL."""


class Crawler:
    def __init__(
        self,
        start_url: str,
        frontier: Frontier,
        sink: Sink,
        *,
        max_depth: int = 3,
        max_pages: int = 500,
        concurrency: int = 2,
        delay: float = 0.5,
        include_subdomains: bool = False,
        ignore_robots: bool = False,
        force_new: bool = False,
        use_sitemap: bool = False,
        stealth: bool = False,
        fetcher: Fetcher | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        fetch_timeout: float = 35.0,
        extra_urls: list[str] | None = None,
        no_follow: bool = False,
        reprocess_urls: list[str] | None = None,
        drain_pending: bool = False,
    ):
        self.start_url = normalize_url(start_url)
        self.seed_host = urlparse(self.start_url).hostname or ""
        self.frontier = frontier
        self.sink = sink
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.concurrency = max(1, concurrency)
        self.include_subdomains = include_subdomains
        self.force_new = force_new
        self.use_sitemap = use_sitemap
        self.max_attempts = max_attempts
        self.fetch_timeout = fetch_timeout
        self.extra_urls = list(extra_urls or [])
        self.no_follow = no_follow
        self.reprocess_urls = list(reprocess_urls or [])
        self.drain_pending = drain_pending
        self.politeness = Politeness(
            user_agent=BOT_USER_AGENT,
            delay=delay,
            ignore_robots=ignore_robots,
            include_subdomains=include_subdomains,
        )
        self.fetcher = fetcher or Fetcher(
            seed_host=self.seed_host,
            include_subdomains=include_subdomains,
            stealth=stealth,
        )
        self._in_flight = 0
        self._flight_lock = asyncio.Lock()
        self._wakeup = asyncio.Event()

    async def run(self) -> dict[str, int]:
        await self.frontier.connect()
        start_sink = getattr(self.sink, "start", None)
        if start_sink is not None:
            await start_sink()
        await self.fetcher.start()
        try:
            await self._prepare_frontier()
            await self._apply_url_targets()
            if self.drain_pending:
                await self._raise_max_for_drain()
            await self.politeness.load_robots(self.fetcher.http, self.start_url)
            if self.use_sitemap and not await self.frontier.get_meta("sitemap_seeded"):
                sitemap_urls = await fetch_sitemap_urls(
                    self.fetcher.http,
                    self.start_url,
                    self.seed_host,
                    self.include_subdomains,
                    max_urls=self.max_pages * 4,
                )
                if sitemap_urls:
                    await self.frontier.enqueue([(url, 0) for url in sitemap_urls])
                    print(f"[SITEMAP] Enqueued {len(sitemap_urls)} URLs")
                await self.frontier.set_meta("sitemap_seeded", "1")

            workers = [
                asyncio.create_task(self._worker(index), name=f"crawler-worker-{index}")
                for index in range(self.concurrency)
            ]
            try:
                await asyncio.gather(*workers)
            except asyncio.CancelledError:
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                raise
        finally:
            try:
                await self.frontier.reset_orphans()
            except Exception:
                pass
            await self.sink.close(self.frontier)
            await self.fetcher.close()
            counts = await self.frontier.counts()
            await self.frontier.close()

        print(
            "[STATS] "
            f"done={counts['done']} failed={counts['failed']} "
            f"skipped={counts['skipped']} skipped_depth={counts['skipped_depth']} "
            f"pending={counts['pending']}"
        )
        return counts

    async def _prepare_frontier(self) -> None:
        has_rows = await self.frontier.has_any_rows()
        stored_seed = await self.frontier.get_meta("seed_url")

        if has_rows and stored_seed and stored_seed != self.start_url and not self.force_new:
            raise CrawlAborted(
                f"Database already has a crawl for {stored_seed!r}. "
                f"Use a different output path or pass --force-new to start over."
            )

        if self.force_new and (has_rows or stored_seed):
            wipe = getattr(self.sink, "wipe", None)
            if wipe is not None:
                await wipe()
            await self.frontier.reset_all()
            has_rows = False

        orphans = await self.frontier.reset_orphans()
        if has_rows:
            counts = await self.frontier.counts()
            print(
                f"[RESUME] seed={stored_seed or self.start_url} "
                f"pending={counts['pending']} done={counts['done']} "
                f"orphans_reset={orphans}"
            )
            if stored_seed is None:
                await self.frontier.set_meta("seed_url", self.start_url)
            return

        await self.frontier.set_meta("seed_url", self.start_url)
        enqueue_seed = not (self.no_follow and self.extra_urls)
        if enqueue_seed:
            await self.frontier.enqueue([(self.start_url, 0)])
            print(f"[NEW START] {self.start_url}")
        else:
            print(
                f"[NEW START] scope={self.start_url} "
                f"(seed not enqueued: --no-follow with target URLs)"
            )

    async def _apply_url_targets(self) -> None:
        if self.extra_urls:
            accepted, rejected = filter_in_scope(
                self.extra_urls, self.seed_host, self.include_subdomains
            )
            for url in rejected:
                print(f"[URL SKIP] out of scope: {url}")
            if accepted:
                await self.frontier.enqueue([(url, 0) for url in accepted])
                print(f"[URL] Enqueued {len(accepted)} target URL(s)")

        if self.reprocess_urls:
            accepted, rejected = filter_in_scope(
                [normalize_url(url) for url in self.reprocess_urls],
                self.seed_host,
                self.include_subdomains,
            )
            for url in rejected:
                print(f"[REPROCESS SKIP] out of scope: {url}")
            if accepted:
                n = await self.frontier.reprocess(accepted)
                print(f"[REPROCESS] Queued {len(accepted)} URL(s) (rows touched≈{n})")
                self._wakeup.set()

    async def _raise_max_for_drain(self) -> None:
        """Raise max_pages so current pending (+ in_progress) can all be claimed."""
        from crawler.status import drain_max_pages

        counts = await self.frontier.counts()
        new_max = drain_max_pages(counts, floor=self.max_pages)
        print(
            f"[DRAIN] pending={counts['pending']} done={counts['done']} "
            f"in_progress={counts['in_progress']} → max_pages={new_max}"
            + (f" (was {self.max_pages})" if new_max != self.max_pages else "")
        )
        self.max_pages = new_max

    async def _worker(self, index: int) -> None:
        del index
        while True:
            claimed = await self.frontier.claim_next(self.max_pages)
            if claimed is None:
                counts = await self.frontier.counts()
                async with self._flight_lock:
                    in_flight = self._in_flight
                if counts["done"] >= self.max_pages:
                    return
                if counts["pending"] == 0 and in_flight == 0:
                    return
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=0.4)
                except asyncio.TimeoutError:
                    pass
                continue

            async with self._flight_lock:
                self._in_flight += 1
            try:
                await self._process(claimed)
            finally:
                async with self._flight_lock:
                    self._in_flight -= 1
                self._wakeup.set()

    async def _process(self, claimed: ClaimedUrl) -> None:
        url = claimed.url
        depth = claimed.depth

        if depth > self.max_depth:
            await self.frontier.mark(url, "skipped_depth", error="max_depth exceeded")
            return

        if not self.politeness.allowed(url):
            await self.frontier.mark(url, "skipped", error="robots.txt disallowed")
            print(f"[ROBOTS] skip {url}")
            return

        print(f"[CRAWLING Depth {depth} attempt {claimed.attempts}] {url}")
        await self.politeness.wait_host(url)

        try:
            result = await asyncio.wait_for(self.fetcher.fetch(url), timeout=self.fetch_timeout)
        except asyncio.TimeoutError:
            result = FetchResult(url, url, None, "", "", False, error="timeout: worker")

        if await self._maybe_retry(claimed, result):
            return

        if result.error and "off-domain" in result.error:
            await self.frontier.mark(
                url, "skipped", http_status=result.status, error=result.error
            )
            print(f"[REDIRECTED OFF-DOMAIN] {url} -> {result.final_url}")
            return

        if result.status in {403, 401}:
            await self.frontier.mark(
                url, "failed", http_status=result.status, error=result.error or "blocked"
            )
            print(f"[BLOCKED {result.status}] {url}")
            return

        if result.status and result.status >= 400:
            await self.frontier.mark(
                url,
                "failed",
                http_status=result.status,
                error=result.error or f"http {result.status}",
            )
            print(f"[HTTP {result.status}] {url}")
            return

        if result.error or not result.html:
            await self.frontier.mark(
                url,
                "failed",
                http_status=result.status,
                error=result.error or "empty body",
            )
            print(f"[ERROR] {url}: {result.error or 'empty body'}")
            return

        title = result.title or ""
        if any(marker in title for marker in WAF_TITLE_MARKERS):
            await self.frontier.mark(url, "failed", http_status=result.status, error="waf")
            print(f"[WAF BLOCKED] {url}")
            return

        try:
            filepath = await self.sink.save(url, title, result.html)
        except Exception as exc:
            await self.frontier.mark(url, "failed", error=f"save: {exc}")
            print(f"[SAVE ERROR] {url}: {exc}")
            return

        await self.frontier.mark(url, "done", http_status=result.status, filepath=filepath)
        print(f"[STORED] {url}")

        if not self.no_follow:
            await self._enqueue_links(result.html, result.final_url or url, depth)

    async def _maybe_retry(self, claimed: ClaimedUrl, result: FetchResult) -> bool:
        retryable = False
        if result.status in RETRYABLE_STATUS:
            retryable = True
        elif result.error and result.error.startswith("timeout:"):
            retryable = True
        if not retryable:
            return False
        if claimed.attempts >= self.max_attempts:
            await self.frontier.mark(
                claimed.url,
                "failed",
                http_status=result.status,
                error=result.error or f"http {result.status}",
            )
            print(f"[GIVE UP] {claimed.url} after {claimed.attempts} attempts")
            return True
        wait = result.retry_after if result.retry_after is not None else 2 ** (claimed.attempts - 1)
        wait = min(max(wait, 0.1), 60.0)
        print(f"[RETRY] {claimed.url} in {wait:.1f}s")
        await asyncio.sleep(wait)
        await self.frontier.requeue_pending(
            claimed.url, error=result.error or f"http {result.status}"
        )
        return True

    async def _enqueue_links(self, html: str, page_url: str, depth: int) -> None:
        pending: list[tuple[str, int]] = []
        skipped_depth: list[tuple[str, int]] = []
        next_depth = depth + 1
        for href in extract_hrefs(html, page_url):
            if not should_enqueue(href, self.seed_host, self.include_subdomains):
                continue
            if next_depth > self.max_depth:
                skipped_depth.append((href, next_depth))
            else:
                pending.append((href, next_depth))
        if pending:
            await self.frontier.enqueue(pending)
            self._wakeup.set()
        if skipped_depth:
            await self.frontier.enqueue_skipped_depth(skipped_depth)
