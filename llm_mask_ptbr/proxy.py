import json
import logging
import time
from collections import Counter

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .payload import add_notice, restore_all, transform_request, transform_response
from .stream import StreamRestorer

log = logging.getLogger("llm_mask_ptbr")

DROPPED = {"host", "content-length", "content-encoding", "transfer-encoding", "connection", "accept-encoding"}
INSPECTED = ("/chat/completions", "/messages", "/messages/count_tokens")
NOTICE = ("Aviso do sistema de privacidade: trechos entre colchetes como [PESSOA_1], [CPF_2] ou [EMAIL_3] não são campos a "
          "preencher. Cada um representa um dado real e válido, protegido antes de chegar a você. Trate o marcador como o "
          "próprio valor: copie-o exatamente, inclusive em chamadas de ferramenta, e nunca peça o valor real nem tente "
          "adivinhá-lo. O sistema troca cada marcador pelo valor verdadeiro automaticamente, antes de o usuário ler a "
          "resposta e antes de a ferramenta ser executada. Exceção: [SENHA_n] e [SEGREDO_n] são segredos. Use-os só no "
          "argumento da ferramenta que precisa do valor (digitar num campo de login, por exemplo). Eles nunca são trocados no "
          "texto da resposta, em mensagens, em notas ou na memória: ali o marcador segue como está, e é assim que deve ser.")


def _headers(headers):
    return {name: value for name, value in headers.items() if name.lower() not in DROPPED}


def _error(status, message):
    return JSONResponse({"error": {"type": "llm_mask_ptbr", "message": message}}, status)


async def _stream(reply, restorer=None):
    try:
        async for chunk in reply.aiter_bytes():
            if out := restorer.feed(chunk) if restorer else chunk:
                yield out
        if restorer and (out := restorer.close()):
            yield out
    finally:
        await reply.aclose()


def create_app(masker, upstream, mode="mask", unmasked_models=(), client=None, notice=NOTICE, secret_tools=()):
    secret_tools = set(secret_tools)

    def for_tool(name):
        return lambda text: masker.restore(text, secrets=name in secret_tools)

    client = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
    stats = {"requests": 0, "found": Counter()}

    async def forward(request, content):
        url = upstream.rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        outgoing = client.build_request(request.method, url, headers=_headers(request.headers), content=content)
        return await client.send(outgoing, stream=True)

    async def restored(reply):
        if reply.headers.get("content-type", "").startswith("text/event-stream"):
            return StreamingResponse(_stream(reply, StreamRestorer(masker, secret_tools)), reply.status_code, _headers(reply.headers))
        try:
            raw = (await reply.aread()).decode()
        finally:
            await reply.aclose()
        try:
            data = json.loads(raw)
            data = transform_response(data, masker.restore, for_tool) if reply.is_success else restore_all(data, masker.restore)
            raw = json.dumps(data, ensure_ascii=False)
        except ValueError:
            raw = masker.restore(raw)
        return Response(raw, reply.status_code, _headers(reply.headers))

    async def inspect(request):
        try:
            payload = json.loads(await request.body())
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return _error(400, "request body is not a JSON object")
        started, found = time.monotonic(), Counter()
        action = "bypass" if payload.get("model") in unmasked_models else mode
        if action == "mask":
            payload = transform_request(payload, lambda text: masker.mask(text, found))
            if notice:
                payload = add_notice(payload, notice, anthropic="/messages" in request.url.path)
        elif action == "shadow":
            transform_request(payload, lambda text: found.update(masker.scan(text)) or text)
        reply = await forward(request, json.dumps(payload, ensure_ascii=False).encode())
        stats["requests"] += 1
        stats["found"] += found
        log.info(json.dumps({"path": request.url.path, "model": payload.get("model"), "action": action, "found": dict(found),
                             "status": reply.status_code, "ms": round((time.monotonic() - started) * 1000)}))
        if action == "mask":
            return await restored(reply)
        return StreamingResponse(_stream(reply), reply.status_code, _headers(reply.headers))

    async def handle(request):
        path = request.url.path
        if path == "/_mask/health":
            return JSONResponse({"status": "ok", "mode": mode})
        if path == "/_mask/stats":
            return JSONResponse({"mode": mode, "requests": stats["requests"], "found": dict(stats["found"])})
        try:
            if request.method in ("GET", "HEAD"):
                reply = await forward(request, None)
                return StreamingResponse(_stream(reply), reply.status_code, _headers(reply.headers))
            if request.method == "POST" and path.endswith(INSPECTED):
                return await inspect(request)
        except httpx.HTTPError as error:
            return _error(502, f"upstream unreachable: {type(error).__name__}")
        return _error(501, f"{request.method} {path} is not inspected by llm-mask-ptbr, so it is not forwarded")

    return Starlette(routes=[Route("/{path:path}", handle, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])])
