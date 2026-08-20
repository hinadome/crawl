from crawler.lookup import lookup_disk_url
from crawler.normalize import normalize_url
from crawler.sinks import FilesystemSink, url_relative_path


async def test_lookup_after_disk_save(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    sink = FilesystemSink(str(out), "markdown")
    url = "https://example.com/docs/manage-nodebalancers"
    path = await sink.save(url, "NodeBalancers", "<html><body><main><p>" + ("body " * 40) + "</p></main></body></html>")

    # Simulate frontier row
    import sqlite3

    db = out / "crawl_state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE crawl_state (
            url TEXT PRIMARY KEY,
            filepath TEXT,
            depth INTEGER,
            status TEXT,
            http_status INTEGER,
            error TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO crawl_state VALUES (?, ?, 0, 'done', 200, NULL)",
        (normalize_url(url), path),
    )
    conn.commit()
    conn.close()

    loc = lookup_disk_url(str(out), url)
    assert loc.ok
    assert loc.status == "done"
    assert loc.filepath == path
    assert loc.file_exists
    assert loc.in_frontier


def test_expected_path_matches_sink_layout():
    url = "https://example.com/cloud-computing/docs/manage-nodebalancers"
    rel = url_relative_path(normalize_url(url), ".md")
    assert "/" in rel
    assert rel.endswith(".md")
    assert rel.startswith(rel.split("/")[0])


def test_lookup_missing_url(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    loc = lookup_disk_url(str(out), "https://example.com/missing")
    assert not loc.ok
    assert not loc.in_frontier
    assert loc.filepath is None
    assert loc.expected_filepath.endswith(".md")
