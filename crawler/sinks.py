from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiosqlite

from crawler.extract import render_content
from crawler.frontier import Frontier


def parse_output_type(output_type: str) -> tuple[str, str]:
    fmt = output_type.lower().strip()
    if fmt in {"md", "markdown"}:
        return "markdown", ".md"
    if fmt in {"html", "htm"}:
        return "html", ".html"
    if fmt == "json":
        return "json", ".json"
    raise ValueError(
        f"Unsupported output_type '{output_type}'. Choose 'markdown', 'html', or 'json'."
    )


def url_relative_path(url: str, ext: str = ".md") -> str:
    """Relative path under output_dir for a URL (hash sharding layout)."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    path = urlparse(url).path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", path)[:60].strip("_") or "index"
    return os.path.join(digest[:2], f"{digest}_{slug}{ext}")


def _url_filename(url: str, ext: str) -> str:
    return url_relative_path(url, ext)


class FilesystemSink:
    def __init__(
        self,
        output_dir: str,
        output_type: str,
        *,
        content_mode: str = "main",
        content_selector: str | None = None,
    ):
        self.output_dir = os.path.abspath(output_dir)
        self.output_type, self.file_ext = parse_output_type(output_type)
        self.content_mode = content_mode
        self.content_selector = content_selector
        os.makedirs(self.output_dir, exist_ok=True)

    async def save(self, url: str, title: str, html: str) -> str:
        relative = _url_filename(url, self.file_ext)
        filepath = os.path.join(self.output_dir, relative)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        content, _char_count = render_content(
            self.output_type,
            url,
            html,
            title,
            content_mode=self.content_mode,
            content_selector=self.content_selector,
        )
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(content)
        return filepath

    async def close(self, frontier: Frontier) -> None:
        rows = await frontier.list_done()
        manifest = []
        for row in rows:
            manifest.append(
                {
                    "url": row["url"],
                    "filepath": row["filepath"],
                    "format": self.output_type,
                    "updated_at": row["updated_at"],
                }
            )
        path = os.path.join(self.output_dir, "manifest.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)


class SqliteSink:
    def __init__(
        self,
        db_path: str,
        output_type: str,
        *,
        content_mode: str = "main",
        content_selector: str | None = None,
    ):
        self.db_path = os.path.abspath(db_path)
        self.output_type, _ext = parse_output_type(output_type)
        self.content_mode = content_mode
        self.content_selector = content_selector
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=NORMAL;")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS scraped_pages (
                url TEXT PRIMARY KEY,
                title TEXT,
                content TEXT NOT NULL,
                format TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                scraped_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()

    async def save(self, url: str, title: str, html: str) -> str | None:
        if self._db is None:
            await self.start()
        assert self._db is not None
        content, char_count = render_content(
            self.output_type,
            url,
            html,
            title,
            content_mode=self.content_mode,
            content_selector=self.content_selector,
        )
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO scraped_pages (url, title, content, format, char_count, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                format = excluded.format,
                char_count = excluded.char_count,
                scraped_at = excluded.scraped_at
            """,
            (url, title, content, self.output_type, char_count, now),
        )
        await self._db.commit()
        return None

    async def wipe(self) -> None:
        if self._db is None:
            await self.start()
        assert self._db is not None
        await self._db.execute("DELETE FROM scraped_pages")
        await self._db.commit()

    async def close(self, frontier: Frontier) -> None:
        del frontier
        if self._db is not None:
            await self._db.close()
            self._db = None
