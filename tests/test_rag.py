from rag.types import Document
from rag.chunking.recursive import RecursiveMarkdownChunker, token_count
from rag.retrieve import rrf_fuse
from rag.sources import DiskSource, SqliteSource
from rag.textconv import content_to_markdown


def test_content_to_markdown_json_and_html():
    title, text = content_to_markdown(
        '{"title": "Hello", "markdown": "# Hello\\n\\nWorld"}',
        "json",
    )
    assert title == "Hello"
    assert "World" in text
    _title, html_md = content_to_markdown(
        "<html><body><h1>Hi</h1><p>There</p></body></html>",
        "html",
        "fallback",
    )
    assert "There" in html_md


def test_recursive_chunker_stable_ids_and_overlap():
    body = "# Install\n\n" + ("Install the package with pip. " * 80) + "\n\n## macOS\n\n" + (
        "Use homebrew to install dependencies. " * 80
    )
    doc = Document(
        url="https://example.com/install",
        title="Install",
        text=body,
        content_hash="abc",
        source_format="markdown",
    )
    chunker = RecursiveMarkdownChunker(chunk_size=80, overlap=16)
    chunks = chunker.split(doc)
    assert len(chunks) >= 2
    again = chunker.split(doc)
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in again]
    assert all(token_count(c.text) <= 80 + 5 for c in chunks)
    assert any(c.heading_path and "Install" in c.heading_path for c in chunks)


def test_disk_and_sqlite_sources(tmp_path):
    page = tmp_path / "aa"
    page.mkdir()
    file_path = page / "page.md"
    file_path.write_text("<!-- Source: https://example.com/a -->\n# Alpha\n\nHello world.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    import json

    manifest.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.com/a",
                    "filepath": str(file_path),
                    "format": "markdown",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    docs = list(DiskSource(str(tmp_path)).iter_documents())
    assert len(docs) == 1
    assert docs[0].url == "https://example.com/a"
    assert docs[0].title == "Alpha"

    import sqlite3

    db = tmp_path / "crawl.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE scraped_pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            content TEXT NOT NULL,
            format TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            scraped_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO scraped_pages VALUES (?, ?, ?, ?, ?, ?)",
        (
            "https://example.com/b",
            "Beta",
            "# Beta\n\nFrom sqlite.",
            "markdown",
            10,
            None,
        ),
    )
    conn.commit()
    conn.close()
    sqlite_docs = list(SqliteSource(str(db)).iter_documents())
    assert sqlite_docs[0].title == "Beta"
    assert "sqlite" in sqlite_docs[0].text


def test_rrf_fuse():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    ids = [doc_id for doc_id, _score in fused]
    assert ids[0] in {"a", "b"}
    assert set(ids) == {"a", "b", "c", "d"}
