from __future__ import annotations

import hashlib
import math


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests."""

    def __init__(self, dimensions: int = 64):
        self.model_id = "hash"
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            values[index] += 1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


class LocalEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self.model_id = model
        self._model = None
        self.dimensions = 384

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_id)
            self.dimensions = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [row.tolist() for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        if "bge" in self.model_id.lower():
            text = f"Represent this sentence for searching relevant passages: {text}"
        return self.embed_documents([text])[0]


class OpenAIEmbedder:
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model_id = model
        self.dimensions = 1536 if "small" in model else 3072

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI()
        response = client.embeddings.create(model=self.model_id, input=texts)
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
