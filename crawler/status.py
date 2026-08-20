from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass


STATUSES = (
    "pending",
    "in_progress",
    "done",
    "failed",
    "skipped",
    "skipped_depth",
)


def drain_max_pages(counts: dict[str, int], *, floor: int = 0) -> int:
    """Compute a max_pages high enough to claim every pending / in_progress URL."""
    budget = (
        int(counts.get("done", 0))
        + int(counts.get("pending", 0))
        + int(counts.get("in_progress", 0))
    )
    return max(floor, budget)


@dataclass
class FrontierStatus:
    db_path: str
    counts: dict[str, int]
    total: int
    seed_url: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_frontier_db(*, output_dir: str | None = None, db_path: str | None = None) -> str:
    if db_path:
        return os.path.abspath(db_path)
    if output_dir:
        return os.path.join(os.path.abspath(output_dir), "crawl_state.db")
    raise ValueError("Provide output_dir or db_path")


def frontier_status(db_path: str) -> FrontierStatus:
    """Read status counts from a crawl frontier SQLite database."""
    db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Frontier DB not found: {db_path}")

    counts = {status: 0 for status in STATUSES}
    seed_url = None
    conn = sqlite3.connect(db_path)
    try:
        for status, n in conn.execute(
            "SELECT status, COUNT(*) FROM crawl_state GROUP BY status"
        ):
            counts[status] = int(n)
        try:
            row = conn.execute(
                "SELECT value FROM crawl_meta WHERE key = 'seed_url' LIMIT 1"
            ).fetchone()
            if row:
                seed_url = row[0]
        except sqlite3.OperationalError:
            seed_url = None
    finally:
        conn.close()

    total = sum(counts.values())
    return FrontierStatus(db_path=db_path, counts=counts, total=total, seed_url=seed_url)


def format_frontier_status(status: FrontierStatus) -> str:
    lines = [
        f"db:       {status.db_path}",
        f"seed:     {status.seed_url}",
        f"total:    {status.total}",
    ]
    for key in STATUSES:
        lines.append(f"{key + ':':<16}{status.counts.get(key, 0)}")
    extras = sorted(k for k in status.counts if k not in STATUSES)
    for key in extras:
        lines.append(f"{key + ':':<16}{status.counts[key]}")
    return "\n".join(lines) + "\n"
