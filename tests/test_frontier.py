import asyncio

import pytest

from crawler.frontier import Frontier


@pytest.fixture
async def frontier(tmp_path):
    db = Frontier(str(tmp_path / "frontier.db"))
    await db.connect()
    yield db
    await db.close()


async def test_orphan_in_progress_reset(frontier: Frontier):
    await frontier.enqueue([("https://example.com/a", 0)])
    claimed = await frontier.claim_next(max_pages=10)
    assert claimed is not None
    assert claimed.url.endswith("/a")
    counts = await frontier.counts()
    assert counts["in_progress"] == 1
    n = await frontier.reset_orphans()
    assert n == 1
    counts = await frontier.counts()
    assert counts["pending"] == 1
    assert counts["in_progress"] == 0


async def test_claim_is_exclusive(frontier: Frontier):
    await frontier.enqueue([(f"https://example.com/{i}", 0) for i in range(20)])

    async def claim_many():
        claimed = []
        while True:
            item = await frontier.claim_next(max_pages=100)
            if item is None:
                break
            claimed.append(item.url)
        return claimed

    left, right = await asyncio.gather(claim_many(), claim_many())
    all_urls = left + right
    assert len(all_urls) == 20
    assert len(set(all_urls)) == 20


async def test_first_seen_depth_wins(frontier: Frontier):
    await frontier.enqueue([("https://example.com/x", 1)])
    await frontier.enqueue([("https://example.com/x", 4)])
    claimed = await frontier.claim_next(max_pages=10)
    assert claimed is not None
    assert claimed.depth == 1


async def test_skipped_depth_not_claimed(frontier: Frontier):
    await frontier.enqueue_skipped_depth([("https://example.com/deep", 9)])
    claimed = await frontier.claim_next(max_pages=10)
    assert claimed is None
    counts = await frontier.counts()
    assert counts["skipped_depth"] == 1
