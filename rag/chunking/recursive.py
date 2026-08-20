from __future__ import annotations

import re

import tiktoken

from rag.textconv import embed_text_for, sha256_text
from rag.types import Chunk, Document

_ENCODING = None

SEPARATORS = ("\n## ", "\n### ", "\n#### ", "\n##### ", "\n\n", "\n", ". ", " ", "")


def token_count(text: str) -> int:
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODING.encode(text))


def heading_path_for(prefix: str) -> str | None:
    headings: list[str] = []
    for line in prefix.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            headings = [h for h in headings if h[0] < level]
            headings.append((level, title))
    if not headings:
        return None
    return " > ".join(title for _level, title in headings)


def make_chunk(
    doc: Document,
    body: str,
    index: int,
    *,
    heading_path: str | None = None,
    parent_id: str | None = None,
) -> Chunk:
    body = body.strip()
    embed = embed_text_for(doc.title, doc.url, body)
    return Chunk(
        chunk_id=sha256_text(doc.url, str(index), body)[:24],
        url=doc.url,
        title=doc.title,
        text=body,
        embed_text=embed,
        index=index,
        token_count=token_count(body),
        heading_path=heading_path,
        parent_id=parent_id,
        metadata={"content_hash": doc.content_hash},
    )


def split_recursive(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if token_count(text) <= chunk_size:
        return [text]
    return _split_with_separators(text, chunk_size, overlap, SEPARATORS)


def _split_with_separators(text: str, chunk_size: int, overlap: int, separators: tuple[str, ...]) -> list[str]:
    separator = separators[0] if separators else ""
    rest = separators[1:] if separators else ()
    if separator:
        pieces = _keep_split(text, separator)
    else:
        pieces = list(text)

    merged: list[str] = []
    current = ""
    for piece in pieces:
        candidate = current + piece if current else piece
        if token_count(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            merged.append(current)
            current = _overlap_suffix(current, overlap) + piece
            if token_count(current) > chunk_size:
                if rest:
                    merged.extend(_split_with_separators(piece, chunk_size, overlap, rest))
                    current = ""
                else:
                    merged.extend(_hard_cut(piece, chunk_size, overlap))
                    current = ""
        elif rest:
            merged.extend(_split_with_separators(piece, chunk_size, overlap, rest))
        else:
            merged.extend(_hard_cut(piece, chunk_size, overlap))
    if current:
        merged.append(current)
    return [part.strip() for part in merged if part.strip()]


def _keep_split(text: str, separator: str) -> list[str]:
    if not separator:
        return [text]
    parts = text.split(separator)
    if len(parts) == 1:
        return parts
    rebuilt = [parts[0]]
    for part in parts[1:]:
        rebuilt.append(separator + part)
    return rebuilt


def _overlap_suffix(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) <= overlap:
        return text
    return encoding.decode(tokens[-overlap:])


def _hard_cut(text: str, chunk_size: int, overlap: int) -> list[str]:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    chunks: list[str] = []
    start = 0
    step = max(chunk_size - overlap, 1)
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(encoding.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += step
    return chunks


class RecursiveMarkdownChunker:
    name = "recursive"

    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, doc: Document) -> list[Chunk]:
        parts = split_recursive(doc.text, self.chunk_size, self.overlap)
        chunks: list[Chunk] = []
        cursor = 0
        for index, part in enumerate(parts):
            pos = doc.text.find(part[:80], cursor) if part else -1
            prefix = doc.text[: pos + 1] if pos >= 0 else doc.text
            cursor = max(cursor, pos)
            chunks.append(
                make_chunk(
                    doc,
                    part,
                    index,
                    heading_path=heading_path_for(prefix),
                )
            )
        return chunks
