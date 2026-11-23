import json

import httpx
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from .payload import transform_request, transform_response
from .stream import StreamRestorer

DROPPED = {"host", "content-length", "content-encoding", "transfer-encoding", "connection", "accept-encoding"}


def _headers(headers):
    return {name: value for name, value in headers.items() if name.lower() not in DROPPED}


async def _restored_stream(reply, restorer):
    try:
        async for chunk in reply.aiter_bytes():
            if out := restorer.feed(chunk):
                yield out
        if out := restorer.close():
            yield out
    finally:
        await reply.aclose()


def create_app(masker, upstream, client=None):
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))

    async def handle(request):
        payload = transform_request(json.loads(await request.body()), masker.mask)
        outgoing = client.build_request("POST", upstream.rstrip("/") + request.url.path, headers=_headers(request.headers),
                                        content=json.dumps(payload, ensure_ascii=False).encode())
        reply = await client.send(outgoing, stream=True)
        if reply.headers.get("content-type", "").startswith("text/event-stream"):
            return StreamingResponse(_restored_stream(reply, StreamRestorer(masker)), reply.status_code, _headers(reply.headers))
        try:
            restored = transform_response(json.loads(await reply.aread()), masker.restore)
        finally:
            await reply.aclose()
        return Response(json.dumps(restored, ensure_ascii=False), reply.status_code, _headers(reply.headers))

    return Starlette(routes=[Route("/{path:path}", handle, methods=["GET", "POST"])])
