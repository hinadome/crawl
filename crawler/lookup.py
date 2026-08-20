from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass

from crawler.normalize import normalize_url
from crawler.sinks import parse_output_type, url_relative_path


@dataclass
class DiskUrlLocation:
    url: str
    normalized_url: str
    output_dir: str
    status: str | None
    filepath: str | None
    expected_filepath: str
    file_exists: bool
    in_frontier: bool
    in_manifest: bool
    depth: int | None = None
    http_status: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when frontier says done and the file is present on disk."""
        return (
            self.in_frontier
            and self.status == "done"
            and self.filepath is not None
            and self.file_exists
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def lookup_disk_url(
    output_dir: str,
    url: str,
    *,
    output_type: str = "markdown",
) -> DiskUrlLocation:
    """Resolve where a crawled URL lives under a disk crawl output directory.

    Checks ``crawl_state.db`` (authoritative), ``manifest.json``, and whether
    the recorded filepath exists. Also computes the expected hash path for the
    normalized URL.
    """
    output_dir = os.path.abspath(output_dir)
    normalized = normalize_url(url)
    _fmt, ext = parse_output_type(output_type)
    expected = os.path.join(output_dir, url_relative_path(normalized, ext))

    status = None
    filepath = None
    depth = None
    http_status = None
    error = None
    in_frontier = False

    db_path = os.path.join(output_dir, "crawl_state.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT url, status, filepath, depth, http_status, error
                FROM crawl_state
                WHERE url = ?
                """,
                (normalized,),
            ).fetchone()
            if row is None:
                # try exact raw url then prefix match for convenience
                row = conn.execute(
                    """
                    SELECT url, status, filepath, depth, http_status, error
                    FROM crawl_state
                    WHERE url = ? OR url LIKE ?
                    ORDER BY CASE WHEN url = ? THEN 0 ELSE 1 END, length(url) ASC
                    LIMIT 1
                    """,
                    (url, normalized.rstrip("/") + "%", normalized),
                ).fetchone()
            if row is not None:
                in_frontier = True
                normalized = row["url"]
                status = row["status"]
                filepath = row["filepath"]
                depth = row["depth"]
                http_status = row["http_status"]
                error = row["error"]
                expected = os.path.join(output_dir, url_relative_path(normalized, ext))
        finally:
            conn.close()

    in_manifest = False
    manifest_path = os.path.join(output_dir, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            for entry in manifest:
                if entry.get("url") in {url, normalized}:
                    in_manifest = True
                    if not filepath and entry.get("filepath"):
                        filepath = entry["filepath"]
                    break
        except (json.JSONDecodeError, OSError):
            pass

    check_path = filepath or expected
    file_exists = os.path.isfile(check_path) if check_path else False

    return DiskUrlLocation(
        url=url,
        normalized_url=normalized,
        output_dir=output_dir,
        status=status,
        filepath=filepath,
        expected_filepath=expected,
        file_exists=file_exists,
        in_frontier=in_frontier,
        in_manifest=in_manifest,
        depth=depth,
        http_status=http_status,
        error=error,
    )


def format_disk_lookup(loc: DiskUrlLocation) -> str:
    lines = [
        f"url:            {loc.url}",
        f"normalized:     {loc.normalized_url}",
        f"output_dir:     {loc.output_dir}",
        f"in_frontier:    {loc.in_frontier}",
        f"status:         {loc.status}",
        f"depth:          {loc.depth}",
        f"filepath:       {loc.filepath}",
        f"expected_path:  {loc.expected_filepath}",
        f"file_exists:    {loc.file_exists}",
        f"in_manifest:    {loc.in_manifest}",
        f"ok:             {loc.ok}",
    ]
    if loc.http_status is not None:
        lines.append(f"http_status:    {loc.http_status}")
    if loc.error:
        lines.append(f"error:          {loc.error}")
    return "\n".join(lines) + "\n"
