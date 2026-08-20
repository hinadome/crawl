import uuid

from rag.types import Chunk


def _meta(chunk: Chunk) -> dict:
    meta = {
        "url": chunk.url,
        "title": chunk.title,
        "index": chunk.index,
        "token_count": chunk.token_count,
    }
    if chunk.heading_path:
        meta["heading_path"] = chunk.heading_path
    if chunk.parent_id:
        meta["parent_id"] = chunk.parent_id
    return meta


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
