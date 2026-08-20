import sqlite3

from crawler.status import frontier_status, resolve_frontier_db


def test_resolve_disk_default(tmp_path):
    path = resolve_frontier_db(output_dir=str(tmp_path / "out"))
    assert path.endswith("crawl_state.db")


def test_frontier_status_counts(tmp_path):
    db = tmp_path / "crawl_state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE crawl_state (
            url TEXT PRIMARY KEY,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE crawl_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO crawl_meta VALUES ('seed_url', 'https://example.com')")
    conn.executemany(
        "INSERT INTO crawl_state VALUES (?, ?)",
        [
            ("https://example.com/a", "pending"),
            ("https://example.com/b", "pending"),
            ("https://example.com/c", "done"),
            ("https://example.com/d", "failed"),
        ],
    )
    conn.commit()
    conn.close()

    status = frontier_status(str(db))
    assert status.seed_url == "https://example.com"
    assert status.counts["pending"] == 2
    assert status.counts["done"] == 1
    assert status.counts["failed"] == 1
    assert status.total == 4
