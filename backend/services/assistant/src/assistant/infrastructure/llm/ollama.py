import json
from collections.abc import AsyncIterator

import httpx

from assistant.application.ports import Prompt
from assistant.domain.errors import UpstreamUnavailable


class OllamaLlm:
    def __init__(self, client: httpx.AsyncClient, model: str, base_url: str = "") -> None:
        self._client = client
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama-{self._model}"

    def _payload(self, prompt: Prompt, stream: bool) -> dict[str, object]:
        return {
            "model": self._model,
            "stream": stream,
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.text},
            ],
        }

    async def generate(self, prompt: Prompt) -> str:
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat", json=self._payload(prompt, stream=False)
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise UpstreamUnavailable("ollama chat unavailable") from None
        return str(response.json()["message"]["content"])

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        try:
            async with self._client.stream(
                "POST", f"{self._base_url}/api/chat", json=self._payload(prompt, stream=True)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except httpx.HTTPError:
            raise UpstreamUnavailable("ollama chat unavailable") from None
