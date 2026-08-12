from __future__ import annotations

import gzip

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class GZipRequestMiddleware:
    def __init__(self, app: ASGIApp, max_decompressed_bytes: int = 50 * 1024 * 1024) -> None:
        self.app = app
        self.max_decompressed_bytes = max_decompressed_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_gzip(scope):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        try:
            body = gzip.decompress(b"".join(chunks))
        except (gzip.BadGzipFile, EOFError):
            await _bad_request(send, b'{"detail":"invalid gzip request body"}')
            return
        if len(body) > self.max_decompressed_bytes:
            await _bad_request(send, b'{"detail":"decompressed request body is too large"}', 413)
            return

        sent = False

        async def decompressed_receive() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        scope = dict(scope)
        scope["headers"] = [(key, value) for key, value in scope["headers"]
                            if key not in {b"content-encoding", b"content-length"}]
        await self.app(scope, decompressed_receive, send)


def _is_gzip(scope: Scope) -> bool:
    return any(key == b"content-encoding" and value.lower() == b"gzip" for key, value in scope["headers"])


async def _bad_request(send: Send, body: bytes, status: int = 400) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
