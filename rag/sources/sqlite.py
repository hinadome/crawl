from __future__ import annotations

import sqlite3

from rag.textconv import content_to_markdown, sha256_text
from rag.types import Document


class SqliteSource:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def iter_documents(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT url, title, content, format, scraped_at
                FROM scraped_pages
                """
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            title, text = content_to_markdown(row["content"], row["format"], row["title"] or "")
            if not text.strip():
                continue
            yield Document(
                url=row["url"],
                title=title or row["title"] or row["url"],
                text=text,
                content_hash=sha256_text(text),
                source_format=row["format"],
                scraped_at=row["scraped_at"],
            )
