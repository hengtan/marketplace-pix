import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

from assistant.infrastructure.embedders.hashing import HashingEmbedder


def echo_first_passage(user_text: str) -> str:
    match = re.search(r'<trecho id="1" produto="([^"]+)" preco="([^"]+)">', user_text)
    if not match:
        return "Não encontrei no catálogo nada que corresponda a isso."
    return f"Encontrei {match.group(1)} por {match.group(2)} [1]."


class FakeOllama:
    """A real HTTP server speaking the two Ollama endpoints the adapters use, so the httpx
    code path (streaming NDJSON, timeouts, closed connections) is exercised without Ollama."""

    def __init__(
        self,
        reply: Callable[[str], str] = echo_first_passage,
        dimension: int = 256,
        token_delay: float = 0.0,
    ) -> None:
        self.reply = reply
        self.token_delay = token_delay
        self.embedder = HashingEmbedder(dimension)
        self.client_closed = asyncio.Event()
        self.chat_requests = 0
        self.embed_requests = 0
        self.fail_next = 0
        self.fail_chat = 0
        self._server: asyncio.Server | None = None
        self.port = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> "FakeOllama":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode().split("\r\n")
            path = lines[0].split(" ")[1]
            headers = {
                k.lower(): v for k, v in (line.split(": ", 1) for line in lines[1:] if ": " in line)
            }
            body = json.loads(await reader.readexactly(int(headers.get("content-length", "0"))))
            if self.fail_next > 0:
                self.fail_next -= 1
                await self._send(writer, 503, {"error": "overloaded"})
            elif path == "/api/embed":
                self.embed_requests += 1
                vectors = [self.embedder.embed_one(t) for t in body["input"]]
                await self._send(writer, 200, {"embeddings": vectors})
            elif path == "/api/chat" and self.fail_chat > 0:
                self.fail_chat -= 1
                await self._send(writer, 503, {"error": "overloaded"})
            elif path == "/api/chat":
                self.chat_requests += 1
                await self._chat(reader, writer, body)
            else:
                await self._send(writer, 404, {"error": "not found"})
        except (asyncio.IncompleteReadError, ConnectionError):
            self.client_closed.set()
        finally:
            writer.close()

    async def _chat(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, body: dict[str, Any]
    ) -> None:
        user_text = next(m["content"] for m in body["messages"] if m["role"] == "user")
        answer = self.reply(user_text)
        if not body.get("stream"):
            await self._send(writer, 200, {"message": {"role": "assistant", "content": answer}})
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
        )
        watcher = asyncio.create_task(self._watch(reader))
        try:
            pieces = re.findall(r"\S+\s*", answer)
            for piece in pieces:
                await self._chunk(writer, {"message": {"content": piece}, "done": False})
                await asyncio.sleep(self.token_delay)
                if watcher.done():
                    return
            await self._chunk(writer, {"message": {"content": ""}, "done": True})
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        finally:
            watcher.cancel()

    async def _watch(self, reader: asyncio.StreamReader) -> None:
        if await reader.read(1) == b"":
            self.client_closed.set()

    @staticmethod
    async def _chunk(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload) + "\n").encode()
        writer.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        await writer.drain()

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
            + data
        )
        await writer.drain()
