import json

from rag.config import RagConfig
from rag.pipeline import ingest, query


def _write_crawl(tmp_path, pages: dict[str, str]):
    files = []
    for url, body in pages.items():
        folder = tmp_path / "pages"
        folder.mkdir(exist_ok=True)
        path = folder / (url.replace("https://", "").replace("/", "_") + ".md")
        path.write_text(body, encoding="utf-8")
        files.append({"url": url, "filepath": str(path), "format": "markdown", "updated_at": None})
    (tmp_path / "manifest.json").write_text(json.dumps(files), encoding="utf-8")


def test_chroma_ingest_query_and_incremental(tmp_path):
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
        chunker="recursive",
        chunk_size=128,
        chunk_overlap=16,
        k=4,
    )
    first = ingest(config)
    assert first["indexed"] == 2
    assert first["skipped"] == 0
    second = ingest(config)
    assert second["skipped"] == 2
    assert second["indexed"] == 0
    hits = query(config, "pip install acme widget")
    assert hits
    assert any("install" in hit.chunk.url for hit in hits)


def test_debug_logs_progress(tmp_path, capsys):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    _write_crawl(
        crawl,
        {
            "https://example.com/a": "# A\n\nAlpha page about apples.\n",
        },
    )
    config = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(tmp_path / "index"),
        store="chroma",
        embedder="hash",
        debug=True,
    )
    stats = ingest(config)
    err = capsys.readouterr().err
    assert stats["indexed"] == 1
    assert "[ingest] start" in err
    assert "INDEX" in err
    assert "DONE" in err
    assert "[ingest] finish" in err


def test_switching_store_reindexes(tmp_path, capsys):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    _write_crawl(
        crawl,
        {
            "https://example.com/a": "# A\n\nAlpha page about apples.\n",
            "https://example.com/b": "# B\n\nBeta page about bananas.\n",
        },
    )
    persist = tmp_path / "index"
    chroma = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="chroma",
        embedder="hash",
        debug=True,
    )
    first = ingest(chroma)
    assert first["indexed"] == 2
    assert first["skipped"] == 0

    qdrant = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="qdrant",
        embedder="hash",
        debug=True,
    )
    second = ingest(qdrant)
    err = capsys.readouterr().err
    assert second["indexed"] == 2
    assert second["skipped"] == 0
    assert "store-changed:chroma->qdrant" in err

    third = ingest(qdrant)
    assert third["skipped"] == 2
    assert third["indexed"] == 0


def test_force_reindex_and_prune(tmp_path):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    _write_crawl(
        crawl,
        {
            "https://example.com/a": "# A\n\nAlpha page about apples.\n",
            "https://example.com/b": "# B\n\nBeta page about bananas.\n",
        },
    )
    persist = tmp_path / "index"
    config = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="chroma",
        embedder="hash",
        force_reindex=True,
    )
    ingest(config)
    _write_crawl(crawl, {"https://example.com/a": "# A\n\nAlpha page about apples.\n"})
    config.force_reindex = False
    config.prune = True
    stats = ingest(config)
    assert stats["deleted"] == 1
    assert stats["skipped"] == 1


def test_qdrant_and_hybrid(tmp_path):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    _write_crawl(
        crawl,
        {
            "https://example.com/alpha": "# Alpha\n\nUnique token zebra-zebra lives here.\n",
            "https://example.com/beta": "# Beta\n\nOrdinary words about weather.\n",
        },
    )
    persist = tmp_path / "index"
    config = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="qdrant",
        embedder="hash",
        hybrid=True,
        k=3,
    )
    ingest(config)
    hits = query(config, "zebra-zebra")
    assert hits
    assert any("alpha" in hit.chunk.url for hit in hits)


def test_parent_child_ingest(tmp_path):
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    long = "# Guide\n\n" + ("Parent context about networking. " * 40) + "\n\n## DNS\n\n" + (
        "DNS resolves names to addresses. " * 40
    )
    _write_crawl(crawl, {"https://example.com/guide": long})
    persist = tmp_path / "index"
    config = RagConfig(
        source_type="disk",
        source_path=str(crawl),
        persist_dir=str(persist),
        store="chroma",
        embedder="hash",
        chunker="parent_child",
        child_size=40,
        parent_size=200,
        chunk_overlap=8,
        k=3,
    )
    stats = ingest(config)
    assert stats["chunks"] >= 1
    hits = query(config, "DNS resolves names")
    assert hits
    assert hits[0].chunk.parent_id is None or len(hits[0].chunk.text) >= len("DNS")
