from __future__ import annotations

import sqlite3
from typing import Iterable

from rag.types import Chunk


class Catalog:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                url TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                chunker TEXT NOT NULL,
                embedder TEXT NOT NULL,
                store TEXT,
                scraped_at TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                text TEXT NOT NULL,
                embed_text TEXT NOT NULL,
                idx INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                heading_path TEXT,
                parent_id TEXT,
                is_parent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_columns()
        self._conn.commit()

    def _ensure_columns(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "store" not in columns:
            self._conn.execute("ALTER TABLE documents ADD COLUMN store TEXT")

    def close(self) -> None:
        self._conn.close()

    def get_document(self, url: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM documents WHERE url = ?", (url,)
        ).fetchone()

    def all_urls(self) -> set[str]:
        rows = self._conn.execute("SELECT url FROM documents").fetchall()
        return {row["url"] for row in rows}

    def replace_document(
        self,
        url: str,
        content_hash: str,
        chunker: str,
        embedder: str,
        store: str,
        scraped_at: str | None,
        chunks: Iterable[Chunk],
        parents: Iterable[Chunk] = (),
    ) -> None:
        self._conn.execute("DELETE FROM chunks WHERE url = ?", (url,))
        self._conn.execute(
            """
            INSERT INTO documents (url, content_hash, chunker, embedder, store, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                content_hash = excluded.content_hash,
                chunker = excluded.chunker,
                embedder = excluded.embedder,
                store = excluded.store,
                scraped_at = excluded.scraped_at
            """,
            (url, content_hash, chunker, embedder, store, scraped_at),
        )
        for chunk in chunks:
            self._insert_chunk(chunk, is_parent=False)
        for parent in parents:
            self._insert_chunk(parent, is_parent=True)
        self._conn.commit()

    def _insert_chunk(self, chunk: Chunk, is_parent: bool) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO chunks (
                chunk_id, url, title, text, embed_text, idx, token_count,
                heading_path, parent_id, is_parent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.url,
                chunk.title,
                chunk.text,
                chunk.embed_text,
                chunk.index,
                chunk.token_count,
                chunk.heading_path,
                chunk.parent_id,
                1 if is_parent else 0,
            ),
        )

    def delete_url(self, url: str) -> None:
        self._conn.execute("DELETE FROM chunks WHERE url = ?", (url,))
        self._conn.execute("DELETE FROM documents WHERE url = ?", (url,))
        self._conn.commit()

    def chunk(self, chunk_id: str) -> Chunk | None:
        row = self._conn.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_chunk(row)

    def parent(self, parent_id: str) -> Chunk | None:
        row = self._conn.execute(
            "SELECT * FROM chunks WHERE chunk_id = ? AND is_parent = 1",
            (parent_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_chunk(row)

    def indexed_chunks(self) -> list[Chunk]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE is_parent = 0 ORDER BY url, idx"
        ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def stats(self) -> dict:
        docs = self._conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        chunks = self._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE is_parent = 0"
        ).fetchone()["n"]
        chunkers = [
            row["chunker"]
            for row in self._conn.execute(
                "SELECT DISTINCT chunker FROM documents ORDER BY chunker"
            )
        ]
        embedders = [
            row["embedder"]
            for row in self._conn.execute(
                "SELECT DISTINCT embedder FROM documents ORDER BY embedder"
            )
        ]
        stores = [
            row["store"]
            for row in self._conn.execute(
                "SELECT DISTINCT store FROM documents WHERE store IS NOT NULL ORDER BY store"
            )
        ]
        return {
            "docs": docs,
            "chunks": chunks,
            "chunkers": chunkers,
            "embedders": embedders,
            "stores": stores,
        }


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        url=row["url"],
        title=row["title"] or "",
        text=row["text"],
        embed_text=row["embed_text"],
        index=row["idx"],
        token_count=row["token_count"],
        heading_path=row["heading_path"],
        parent_id=row["parent_id"],
    )
