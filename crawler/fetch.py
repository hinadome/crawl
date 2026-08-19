from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from crawler.extract import looks_like_spa_shell, title_from_html
from crawler.normalize import host_in_scope, normalize_url

BOT_USER_AGENT = "ScrapperBot/0.1"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    html: str
    title: str
    used_browser: bool
    error: str | None = None
    retry_after: float | None = None


class Fetcher:
    def __init__(
        self,
        seed_host: str,
        include_subdomains: bool,
        stealth: bool = False,
        context_recycle_every: int = 25,
    ):
        self.seed_host = seed_host
        self.include_subdomains = include_subdomains
        self.stealth = stealth
        self.context_recycle_every = context_recycle_every
        self._http: httpx.AsyncClient | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._pages_since_recycle = 0
        self._open_pages = 0
        self._browser_lock = asyncio.Lock()

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("Fetcher.start() was not called")
        return self._http

    async def start(self) -> None:
        headers = {"User-Agent": BOT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        self._http = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
        )

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _ensure_browser_unlocked(self) -> BrowserContext:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            launch_args = ["--no-sandbox"]
            if self.stealth:
                launch_args.append("--disable-blink-features=AutomationControlled")
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
            )
        if self._context is None:
            self._context = await self._new_context()
        return self._context

    async def _new_context(self) -> BrowserContext:
        assert self._browser is not None
        ua = BROWSER_USER_AGENT if self.stealth else BOT_USER_AGENT
        ctx = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1440, "height": 900},
        )
        if self.stealth:
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        return ctx

    def _in_scope(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host_in_scope(host, self.seed_host, self.include_subdomains)

    async def fetch(self, url: str) -> FetchResult:
        http_result = await self._fetch_http(url)
        if http_result.error:
            return http_result
        if http_result.status and http_result.status >= 400:
            return http_result
        if looks_like_spa_shell(http_result.html):
            browser_result = await self._fetch_browser(url)
            if not browser_result.error and browser_result.html:
                return browser_result
        return http_result

    async def _fetch_http(self, url: str) -> FetchResult:
        try:
            response = await self.http.get(url)
        except httpx.TimeoutException as exc:
            return FetchResult(url, url, None, "", "", False, error=f"timeout: {exc}")
        except httpx.HTTPError as exc:
            return FetchResult(url, url, None, "", "", False, error=str(exc))

        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        final_url = normalize_url(str(response.url))
        if not self._in_scope(final_url):
            return FetchResult(
                url,
                final_url,
                response.status_code,
                "",
                "",
                False,
                error=f"redirected off-domain: {final_url}",
                retry_after=retry_after,
            )
        content_type = response.headers.get("content-type", "")
        html = response.text if "html" in content_type.lower() or not content_type else ""
        if not html and response.status_code < 400:
            html = response.text
        title = title_from_html(html) if html else ""
        return FetchResult(
            url,
            final_url,
            response.status_code,
            html,
            title,
            False,
            retry_after=retry_after,
        )

    async def _fetch_browser(self, url: str) -> FetchResult:
        async with self._browser_lock:
            context = await self._ensure_browser_unlocked()
            self._open_pages += 1
            page = await context.new_page()
        try:
            page.set_default_timeout(15000)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,mp4,woff,woff2}", lambda r: r.abort())
            await page.route(
                "**/*{analytics,telemetry,google-analytics,segment}*",
                lambda r: r.abort(),
            )
            response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            final_url = normalize_url(page.url)
            if not self._in_scope(final_url):
                return FetchResult(
                    url,
                    final_url,
                    response.status if response else None,
                    "",
                    "",
                    True,
                    error=f"redirected off-domain: {final_url}",
                )
            try:
                await page.wait_for_selector("body", timeout=5000, state="attached")
            except Exception:
                pass
            html = await page.content()
            title = await page.title()
            status = response.status if response else None
            return FetchResult(url, final_url, status, html, title, True)
        except Exception as exc:
            return FetchResult(url, url, None, "", "", True, error=str(exc))
        finally:
            await page.close()
            async with self._browser_lock:
                self._open_pages -= 1
                self._pages_since_recycle += 1
                if (
                    self._open_pages == 0
                    and self._context is not None
                    and self._pages_since_recycle >= self.context_recycle_every
                ):
                    await self._context.close()
                    self._context = await self._new_context()
                    self._pages_since_recycle = 0


def _parse_retry_after(header: str | None) -> float | None:
    if not header:
        return None
    header = header.strip()
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        from datetime import datetime, timezone

        when = parsedate_to_datetime(header)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except (TypeError, ValueError, OverflowError):
        return None
