from __future__ import annotations

from rag.chunking.recursive import RecursiveMarkdownChunker, make_chunk, split_recursive
from rag.types import Chunk, Document


class ParentChildChunker:
    name = "parent_child"

    def __init__(
        self,
        parent_size: int = 1024,
        child_size: int = 160,
        overlap: int = 32,
    ):
        self.parent_size = parent_size
        self.child_size = child_size
        self.overlap = overlap
        self._parents: dict[str, Chunk] = {}

    def split(self, doc: Document) -> list[Chunk]:
        self._parents = {}
        parent_texts = split_recursive(doc.text, self.parent_size, self.overlap)
        children: list[Chunk] = []
        child_index = 0
        for parent_index, parent_text in enumerate(parent_texts):
            parent = make_chunk(doc, parent_text, parent_index * 1000, heading_path=None)
            self._parents[parent.chunk_id] = parent
            child_parts = split_recursive(parent_text, self.child_size, self.overlap)
            if not child_parts:
                continue
            if len(child_parts) == 1:
                chunk = make_chunk(
                    doc,
                    child_parts[0],
                    child_index,
                    heading_path=parent.heading_path,
                    parent_id=parent.chunk_id,
                )
                children.append(chunk)
                child_index += 1
                continue
            for part in child_parts:
                children.append(
                    make_chunk(
                        doc,
                        part,
                        child_index,
                        heading_path=parent.heading_path,
                        parent_id=parent.chunk_id,
                    )
                )
                child_index += 1
        return children

    def parent_for(self, parent_id: str) -> Chunk | None:
        return self._parents.get(parent_id)
