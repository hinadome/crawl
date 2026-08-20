from __future__ import annotations

import json
import os

from rag.textconv import content_to_markdown, sha256_text
from rag.types import Document


class DiskSource:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def iter_documents(self):
        manifest_path = os.path.join(self.output_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"No manifest.json in {self.output_dir}")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        for entry in manifest:
            filepath = entry.get("filepath")
            url = entry.get("url")
            if not filepath or not url:
                continue
            if not os.path.exists(filepath):
                continue
            with open(filepath, encoding="utf-8") as handle:
                raw = handle.read()
            fmt = entry.get("format") or "markdown"
            title, text = content_to_markdown(raw, fmt)
            if not text.strip():
                continue
            yield Document(
                url=url,
                title=title or url,
                text=text,
                content_hash=sha256_text(text),
                source_format=fmt,
                scraped_at=entry.get("updated_at"),
                extra={"filepath": filepath},
            )
