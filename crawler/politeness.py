from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

import httpx

from crawler.normalize import host_in_scope, normalize_url, should_enqueue


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


class Politeness:
    def __init__(
        self,
        user_agent: str,
        delay: float = 0.5,
        ignore_robots: bool = False,
        include_subdomains: bool = False,
    ):
        self.user_agent = user_agent
        self.delay = delay
        self.ignore_robots = ignore_robots
        self.include_subdomains = include_subdomains
        self._robots = RobotFileParser()
        self._robots_loaded = False
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._map_lock = asyncio.Lock()

    async def load_robots(self, client: httpx.AsyncClient, seed_url: str) -> None:
        if self.ignore_robots:
            self._robots_loaded = True
            return
        parsed = urlparse(seed_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = await client.get(robots_url, timeout=15.0, follow_redirects=True)
            body = response.text if response.status_code == 200 else ""
        except httpx.HTTPError:
            body = ""
        self._robots = RobotFileParser()
        self._robots.set_url(robots_url)
        self._robots.parse(body.splitlines())
        self._robots_loaded = True

    def allowed(self, url: str) -> bool:
        if self.ignore_robots or not self._robots_loaded:
            return True
        try:
            return self._robots.can_fetch(self.user_agent, url)
        except Exception:
            return True

    async def wait_host(self, url: str) -> None:
        if self.delay <= 0:
            return
        host = (urlparse(url).hostname or "").lower()
        async with self._map_lock:
            lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last_request.get(host, 0.0)
            wait_for = self.delay - (time.monotonic() - last)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request[host] = time.monotonic()


async def fetch_sitemap_urls(
    client: httpx.AsyncClient,
    seed_url: str,
    seed_host: str,
    include_subdomains: bool,
    *,
    max_urls: int = 5000,
) -> list[str]:
    parsed = urlparse(seed_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    return await _parse_sitemap(
        client,
        sitemap_url,
        seed_url,
        seed_host,
        include_subdomains,
        max_urls=max_urls,
        depth=0,
    )


async def _parse_sitemap(
    client: httpx.AsyncClient,
    sitemap_url: str,
    seed_url: str,
    seed_host: str,
    include_subdomains: bool,
    *,
    max_urls: int,
    depth: int,
) -> list[str]:
    if depth > 3:
        return []
    try:
        response = await client.get(sitemap_url, timeout=20.0, follow_redirects=True)
        if response.status_code != 200 or not response.content:
            return []
        root = ET.fromstring(response.content)
    except (httpx.HTTPError, ET.ParseError):
        return []

    found: list[str] = []
    for child in list(root):
        kind = _local_name(child.tag)
        loc_el = None
        for sub in child:
            if _local_name(sub.tag) == "loc":
                loc_el = sub
                break
        if loc_el is None or not loc_el.text:
            continue
        loc = loc_el.text.strip()
        if kind == "sitemap":
            nested = await _parse_sitemap(
                client,
                loc,
                seed_url,
                seed_host,
                include_subdomains,
                max_urls=max_urls - len(found),
                depth=depth + 1,
            )
            found.extend(nested)
            if len(found) >= max_urls:
                return found[:max_urls]
            continue
        normalized = normalize_url(loc, seed_url)
        if should_enqueue(normalized, seed_host, include_subdomains) and host_in_scope(
            urlparse(normalized).hostname or "",
            seed_host,
            include_subdomains,
        ):
            found.append(normalized)
            if len(found) >= max_urls:
                return found
    return found
