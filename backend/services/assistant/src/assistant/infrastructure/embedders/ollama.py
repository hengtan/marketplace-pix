from collections.abc import Sequence

import httpx

from assistant.domain.errors import UpstreamUnavailable


class OllamaEmbedder:
    def __init__(
        self, client: httpx.AsyncClient, model: str, dimension: int, base_url: str = ""
    ) -> None:
        self._client = client
        self._model = model
        self._dimension = dimension
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama-{self._model}-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                f"{self._base_url}/api/embed", json={"model": self._model, "input": list(texts)}
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise UpstreamUnavailable("ollama embeddings unavailable") from None
        vectors: list[list[float]] = response.json()["embeddings"]
        if any(len(v) != self._dimension for v in vectors):
            raise UpstreamUnavailable(
                f"ollama returned vectors that do not have {self._dimension} dimensions"
            )
        return vectors
