from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable

import aiosqlite

STATUSES = (
    "pending",
    "in_progress",
    "done",
    "failed",
    "skipped_depth",
    "skipped",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimedUrl:
    __slots__ = ("url", "depth", "attempts")

    def __init__(self, url: str, depth: int, attempts: int):
        self.url = url
        self.depth = depth
        self.attempts = attempts


class Frontier:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Frontier is not connected")
        return self._db

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=NORMAL;")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_state (
                url TEXT PRIMARY KEY,
                canonical_url TEXT,
                depth INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                http_status INTEGER,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                filepath TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_meta(self, key: str) -> str | None:
        async with self._lock:
            async with self.db.execute(
                "SELECT value FROM crawl_meta WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return None if row is None else row["value"]

    async def set_meta(self, key: str, value: str) -> None:
        async with self._lock:
            await self.db.execute(
                """
                INSERT INTO crawl_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            await self.db.commit()

    async def has_any_rows(self) -> bool:
        async with self._lock:
            async with self.db.execute("SELECT 1 FROM crawl_state LIMIT 1") as cursor:
                return await cursor.fetchone() is not None

    async def reset_all(self) -> None:
        async with self._lock:
            await self.db.execute("DELETE FROM crawl_state")
            await self.db.execute("DELETE FROM crawl_meta")
            await self.db.commit()

    async def reset_orphans(self) -> int:
        async with self._lock:
            cursor = await self.db.execute(
                """
                UPDATE crawl_state
                SET status = 'pending', updated_at = ?
                WHERE status = 'in_progress'
                """,
                (_now(),),
            )
            await self.db.commit()
            return cursor.rowcount or 0

    async def enqueue(self, items: Iterable[tuple[str, int]]) -> None:
        records = [(url, url, depth, "pending", _now()) for url, depth in items]
        if not records:
            return
        async with self._lock:
            await self.db.executemany(
                """
                INSERT INTO crawl_state (url, canonical_url, depth, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                records,
            )
            await self.db.commit()

    async def enqueue_skipped_depth(self, items: Iterable[tuple[str, int]]) -> None:
        records = [(url, url, depth, "skipped_depth", _now()) for url, depth in items]
        if not records:
            return
        async with self._lock:
            await self.db.executemany(
                """
                INSERT INTO crawl_state (url, canonical_url, depth, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                records,
            )
            await self.db.commit()

    async def claim_next(self, max_pages: int) -> ClaimedUrl | None:
        async with self._lock:
            async with self.db.execute(
                "SELECT COUNT(*) AS n FROM crawl_state WHERE status = 'done'"
            ) as cursor:
                done = (await cursor.fetchone())["n"]
            async with self.db.execute(
                "SELECT COUNT(*) AS n FROM crawl_state WHERE status = 'in_progress'"
            ) as cursor:
                in_progress = (await cursor.fetchone())["n"]
            if done + in_progress >= max_pages:
                return None

            cursor = await self.db.execute(
                """
                UPDATE crawl_state
                SET status = 'in_progress',
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE url = (
                    SELECT url FROM crawl_state
                    WHERE status = 'pending'
                    ORDER BY depth ASC, url ASC
                    LIMIT 1
                )
                AND status = 'pending'
                RETURNING url, depth, attempts
                """,
                (_now(),),
            )
            row = await cursor.fetchone()
            await self.db.commit()
            if row is None:
                return None
            return ClaimedUrl(row["url"], row["depth"], row["attempts"])

    async def has_pending(self) -> bool:
        async with self._lock:
            async with self.db.execute(
                "SELECT 1 FROM crawl_state WHERE status = 'pending' LIMIT 1"
            ) as cursor:
                return await cursor.fetchone() is not None

    async def mark(
        self,
        url: str,
        status: str,
        *,
        http_status: int | None = None,
        error: str | None = None,
        filepath: str | None = None,
    ) -> None:
        if status not in STATUSES:
            raise ValueError(f"Invalid status {status}")
        async with self._lock:
            await self.db.execute(
                """
                UPDATE crawl_state
                SET status = ?,
                    http_status = COALESCE(?, http_status),
                    error = ?,
                    filepath = COALESCE(?, filepath),
                    updated_at = ?
                WHERE url = ?
                """,
                (status, http_status, error, filepath, _now(), url),
            )
            await self.db.commit()

    async def requeue_pending(self, url: str, error: str | None = None) -> None:
        async with self._lock:
            await self.db.execute(
                """
                UPDATE crawl_state
                SET status = 'pending',
                    error = ?,
                    updated_at = ?
                WHERE url = ?
                """,
                (error, _now(), url),
            )
            await self.db.commit()

    async def counts(self) -> dict[str, int]:
        result = {status: 0 for status in STATUSES}
        async with self._lock:
            async with self.db.execute(
                "SELECT status, COUNT(*) AS n FROM crawl_state GROUP BY status"
            ) as cursor:
                async for row in cursor:
                    result[row["status"]] = row["n"]
        return result

    async def list_done(self) -> list[aiosqlite.Row]:
        async with self._lock:
            async with self.db.execute(
                """
                SELECT url, filepath, updated_at
                FROM crawl_state
                WHERE status = 'done'
                ORDER BY updated_at ASC
                """
            ) as cursor:
                return list(await cursor.fetchall())
