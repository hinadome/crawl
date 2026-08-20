import json

from rag.config import RagConfig
from rag.pipeline import ingest
from rag.review import (
    ReviewSession,
    format_text_report,
    load_gold,
    metrics_for_queries,
    review_to_json,
    url_matches_gold,
)


def _write_crawl(tmp_path, pages: dict[str, str]):
    files = []
    for url, body in pages.items():
        folder = tmp_path / "pages"
        folder.mkdir(exist_ok=True)
        path = folder / (url.replace("https://", "").replace("/", "_") + ".md")
        path.write_text(body, encoding="utf-8")
        files.append({"url": url, "filepath": str(path), "format": "markdown", "updated_at": None})
    (tmp_path / "manifest.json").write_text(json.dumps(files), encoding="utf-8")


def _index(tmp_path):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    _write_crawl(
        crawl,
        {
            "https://example.com/install": "# Install\n\nInstall the acme widget using pip install acme.\n",
            "https://example.com/faq": "# FAQ\n\nThe sky is blue on a clear day.\n",
        },
    )
    persist = tmp_path / "index"
    config = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="chroma",
        embedder="hash",
        k=4,
    )
    ingest(config)
    return config


def test_url_prefix_gold_match():
    assert url_matches_gold("https://example.com/docs/install", "https://example.com/docs")
    assert not url_matches_gold("https://example.com/other", "https://example.com/docs")


def test_compare_json_has_dense_and_bm25(tmp_path):
    config = _index(tmp_path)
    session = ReviewSession(config)
    try:
        review = session.review_query("pip install acme widget", compare=True)
        payload = review_to_json(review, compare=True, snippet_chars=120)
        assert "dense" in payload["channels"]
        assert "bm25" in payload["channels"]
        assert "rrf" in payload["channels"]
        assert "jaccard_dense_bm25" in payload["overlap"]
    finally:
        session.close()


def test_text_report_includes_url_and_snippet(tmp_path):
    config = _index(tmp_path)
    session = ReviewSession(config)
    try:
        review = session.review_query("pip install acme")
        text = format_text_report(review, compare=False, snippet_chars=80)
        assert "https://example.com/install" in text
        assert "snippet:" in text
        assert "docs=" in text
    finally:
        session.close()


def test_gold_hit_and_miss(tmp_path):
    config = _index(tmp_path)
    session = ReviewSession(config)
    try:
        hit = session.review_query(
            "pip install acme widget",
            expected_urls=["https://example.com/install"],
        )
        miss = session.review_query(
            "pip install acme widget",
            expected_urls=["https://example.com/does-not-exist"],
        )
        hit_metrics = metrics_for_queries(
            [
                {
                    "query": hit.query,
                    "expected_urls": ["https://example.com/install"],
                    "rank": hit.gold["rank"],
                    "found_urls": hit.gold["found_urls"],
                    "missed_urls": hit.gold["missed_urls"],
                }
            ]
        )
        miss_metrics = metrics_for_queries(
            [
                {
                    "query": miss.query,
                    "expected_urls": ["https://example.com/does-not-exist"],
                    "rank": miss.gold["rank"],
                    "found_urls": miss.gold["found_urls"],
                    "missed_urls": miss.gold["missed_urls"],
                }
            ]
        )
        assert hit_metrics["hit_at_k"] == 1.0
        assert miss_metrics["hit_at_k"] == 0.0
        assert miss.gold["rank"] is None
    finally:
        session.close()


def test_load_gold(tmp_path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps({"query": "install?", "expected_urls": ["https://example.com/install"]}) + "\n",
        encoding="utf-8",
    )
    rows = load_gold(str(path))
    assert rows[0]["query"] == "install?"
    assert rows[0]["expected_urls"] == ["https://example.com/install"]
