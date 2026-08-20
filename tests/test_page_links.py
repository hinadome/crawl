from crawler.page_links import (
    extract_links_from_content,
    extract_links_from_markdown,
    list_links_from_disk_url,
)


def test_extract_markdown_links():
    md = """
# Title
See [Next](/docs/next) and [External](https://example.com/x).
Also <https://example.com/auto> and [skip](#section).
"""
    links = extract_links_from_markdown(md, "https://techdocs.example.com/docs/page")
    assert "https://techdocs.example.com/docs/next" in links
    assert "https://example.com/x" in links
    assert "https://example.com/auto" in links
    assert not any("#section" in u for u in links)


def test_extract_html_content():
    html = '<html><body><a href="/a">A</a><a href="https://ex.com/b">B</a></body></html>'
    links = extract_links_from_content(html, "https://example.com/p", kind="html")
    assert links == ["https://example.com/a", "https://ex.com/b"]


def test_list_links_from_disk_file(tmp_path):
    out = tmp_path / "scraped_output"
    shard = out / "ab"
    shard.mkdir(parents=True)
    path = shard / "ab123_docs_page.md"
    path.write_text(
        "<!-- Source: https://example.com/docs/page -->\n"
        "# Page\n\nGo to [Install](/docs/install) and [Home](https://example.com/).\n",
        encoding="utf-8",
    )

    import sqlite3

    db = out / "crawl_state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE crawl_state (
            url TEXT PRIMARY KEY,
            status TEXT,
            filepath TEXT,
            depth INTEGER,
            http_status INTEGER,
            error TEXT
        )
        """
    )
    url = "https://example.com/docs/page"
    conn.execute(
        "INSERT INTO crawl_state VALUES (?, 'done', ?, 0, 200, NULL)",
        (url, str(path)),
    )
    conn.commit()
    conn.close()

    result = list_links_from_disk_url(str(out), url)
    assert result.source_path == str(path)
    assert "https://example.com/docs/install" in result.links
    assert "https://example.com/" in result.links


def test_list_links_from_sqlite_db(tmp_path):
    import sqlite3

    from crawler.page_links import list_links_from_db_url

    db = tmp_path / "crawl_data.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE crawl_state (
            url TEXT PRIMARY KEY,
            status TEXT,
            filepath TEXT,
            depth INTEGER,
            http_status INTEGER,
            error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE scraped_pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            content TEXT NOT NULL,
            format TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            scraped_at TEXT NOT NULL
        )
        """
    )
    url = "https://example.com/docs/page"
    content = (
        "<!-- Source: https://example.com/docs/page -->\n"
        "# Page\n\nSee [Next](/docs/next) and [Ext](https://other.example/x).\n"
    )
    conn.execute(
        "INSERT INTO crawl_state VALUES (?, 'done', NULL, 0, 200, NULL)",
        (url,),
    )
    conn.execute(
        "INSERT INTO scraped_pages VALUES (?, 'Page', ?, 'markdown', ?, '2026-01-01')",
        (url, content, len(content)),
    )
    conn.commit()
    conn.close()

    result = list_links_from_db_url(str(db), url)
    assert result.store == "sqlite"
    assert result.source and result.source.startswith("sqlite:")
    assert result.location.ok
    assert "https://example.com/docs/next" in result.links
    assert "https://other.example/x" in result.links
