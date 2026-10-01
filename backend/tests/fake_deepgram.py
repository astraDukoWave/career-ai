"""A local fake of Deepgram's live WebSocket API for the tests.

Each connection runs the next scripted behaviour. Only 127.0.0.1, no key.
"""

import json

from websockets.asyncio.server import serve

FRAME = b"\x01\x00" * 1600  # 100 ms of 16 kHz linear16


class FakeDeepgram:
    """Local WebSocket server; each connection runs the next behaviour."""

    def __init__(self, *behaviours, reject=None):
        self.behaviours = list(behaviours)
        self.reject = reject  # (request) -> HTTPStatus | None
        self.connections: list[dict] = []
        self.requests: list[str] = []

    def process_request(self, connection, request):
        self.requests.append(request.path)
        status = self.reject(request) if self.reject else None
        return connection.respond(status, "rejected\n") if status else None

    async def handler(self, ws):
        conn = {"path": ws.request.path, "headers": ws.request.headers, "audio": bytearray(),
                "texts": [], "closed": False}
        self.connections.append(conn)
        try:
            await self.behaviours[len(self.connections) - 1](ws, conn)
        finally:
            conn["closed"] = True

    def serve(self):
        """`async with fake.serve() as server`; the base URL is `url_of(server)`."""
        return serve(self.handler, "127.0.0.1", 0, process_request=self.process_request)


def url_of(server) -> str:
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/listen"


def answer(messages=(), after_frames=1, drop_after_frames=None):
    """Send `messages` once `after_frames` arrived; close on CloseStream (or drop)."""

    async def behaviour(ws, conn):
        sent = not messages
        async for msg in ws:
            if isinstance(msg, bytes):
                conn["audio"] += msg
            else:
                conn["texts"].append(json.loads(msg))
                if conn["texts"][-1].get("type") == "CloseStream":
                    await ws.close(1000)
                    return
            frames = len(conn["audio"]) // len(FRAME)
            if drop_after_frames is not None and frames >= drop_after_frames:
                await ws.close(1011, "NET-0001")
                return
            if not sent and frames >= after_frames:
                for message in messages:
                    await ws.send(json.dumps(message))
                sent = True

    return behaviour


async def with_fake(fake: FakeDeepgram, body):
    async with fake.serve() as server:
        return await body(url_of(server))
