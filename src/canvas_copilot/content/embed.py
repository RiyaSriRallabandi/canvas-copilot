"""Turn text into vectors with a local embedding model (Ollama)."""

from __future__ import annotations

import httpx

EMBED_DIM = 768  # nomic-embed-text


class EmbedError(RuntimeError):
    pass


class Embedder:
    def __init__(
        self,
        model: str = "nomic-embed-text",
        ollama_host: str = "http://localhost:11434",
        batch_size: int = 64,
    ) -> None:
        self.model = model
        self.host = ollama_host.rstrip("/")
        self.batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed-text is trained with an asymmetric task prefix.
        return self._embed([f"search_document: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"search_query: {text}"])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            resp = httpx.post(
                f"{self.host}/api/embed",
                json={"model": self.model, "input": batch},
                timeout=120,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbedError(
                f"Could not reach the embedding model at {self.host} ({exc}). "
                f"Is Ollama running, and is `{self.model}` pulled?"
            ) from exc
        embeddings = resp.json().get("embeddings")
        if not embeddings or len(embeddings) != len(batch):
            raise EmbedError(f"Unexpected embedding response for {len(batch)} inputs.")
        return embeddings
