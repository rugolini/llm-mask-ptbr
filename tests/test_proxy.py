import json
import unittest

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from llm_mask_ptbr.detectors import BUILTIN, dictionary
from llm_mask_ptbr.engine import Masker
from llm_mask_ptbr.proxy import create_app

SECRETS = ["Maria Souza", "529.982.247-25", "maria@exemplo.com.br", "Boa Vista"]


def pieces(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


def sse(events):
    lines = [(f"event: {e['type']}\n" if "type" in e else "") + f"data: {json.dumps(e)}\n\n" for e in events]
    return StreamingResponse(iter(line.encode() for line in lines), media_type="text/event-stream")


def received_events(response):
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:") and "[DONE]" not in line]


class ProxyCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.seen = []
        self.reply = lambda body: JSONResponse({})

        async def upstream(request):
            raw = (await request.body()).decode()
            self.seen.append({"method": request.method, "path": request.url.path, "raw": raw, "headers": request.headers})
            return self.reply(json.loads(raw) if raw else None)

        self.upstream = Starlette(routes=[Route("/{path:path}", upstream, methods=["GET", "POST"])])

    def proxy(self, transport=None, **options):
        masker = Masker([*BUILTIN.values(), dictionary({"PESSOA": ["Maria Souza"], "LOCAL": ['Sítio "Boa Vista"']})])
        upstream = httpx.AsyncClient(transport=transport or httpx.ASGITransport(app=self.upstream))
        options.setdefault("notice", "")
        app = create_app(masker, "http://upstream", client=upstream, **options)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://proxy")

    def assertNothingLeaked(self):
        for request in self.seen:
            for secret in SECRETS:
                self.assertNotIn(secret, request["raw"])


class OpenAIChatTest(ProxyCase):
    async def test_the_provider_sees_tokens_and_the_client_gets_the_real_values_back(self):
        tools = [{"type": "function", "function": {"name": "send_email", "parameters": {"type": "object"}}}]
        body = {"model": "coordenacao", "tools": tools, "messages": [
            {"role": "system", "content": "Você atende Maria Souza."},
            {"role": "user", "content": "Meu CPF é 529.982.247-25"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "send_email", "arguments": json.dumps({"to": "maria@exemplo.com.br", "cc": ["Maria Souza"]})}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "enviado para maria@exemplo.com.br"},
            {"role": "user", "content": [{"type": "text", "text": "Avise Maria Souza"}]},
        ]}

        def model(received):
            name = received["messages"][-1]["content"][0]["text"].removeprefix("Avise ")
            to = json.loads(received["messages"][2]["tool_calls"][0]["function"]["arguments"])["to"]
            return JSONResponse({"id": "x", "model": "coordenacao", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": f"Aviso enviado a {name}",
                "tool_calls": [{"id": "call_2", "type": "function", "function": {
                    "name": "send_email", "arguments": json.dumps({"to": to, "subject": f'Olá "{name}"'})}}]}}]})

        self.reply = model
        async with self.proxy() as client:
            response = await client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer k"})

        self.assertNothingLeaked()
        sent = json.loads(self.seen[0]["raw"])
        self.assertEqual((self.seen[0]["path"], self.seen[0]["headers"]["authorization"]), ("/v1/chat/completions", "Bearer k"))
        self.assertEqual((sent["model"], sent["tools"], sent["messages"][3]["tool_call_id"]), ("coordenacao", tools, "call_1"))
        self.assertEqual([m["role"] for m in sent["messages"]], ["system", "user", "assistant", "tool", "user"])
        message = response.json()["choices"][0]["message"]
        self.assertEqual(message["content"], "Aviso enviado a Maria Souza")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]),
                         {"to": "maria@exemplo.com.br", "subject": 'Olá "Maria Souza"'})
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "send_email")

    async def test_tokens_split_across_stream_chunks_are_restored(self):
        text = "Avise Maria Souza (maria@exemplo.com.br), [veja] [TODO_1] e a lista [A, B] fim ["
        arguments = json.dumps({"to": "maria@exemplo.com.br", "body": 'Maria Souza no Sítio "Boa Vista"\n'})
        body = {"model": "m", "stream": True, "messages": [
            {"role": "user", "content": text},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "send_email", "arguments": arguments}}]}]}
        for size in range(1, 12):
            def model(received):
                chunk = lambda delta, finish=None: {"id": "c", "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish}]}
                call = lambda function: chunk({"tool_calls": [{"index": 0, **function}]})
                masked_arguments = received["messages"][1]["tool_calls"][0]["function"]["arguments"]
                return sse([chunk({"role": "assistant", "content": ""}),
                            *[chunk({"content": piece}) for piece in pieces(received["messages"][0]["content"], size)],
                            call({"id": "call_9", "type": "function", "function": {"name": "send_email", "arguments": ""}}),
                            *[call({"function": {"arguments": piece}}) for piece in pieces(masked_arguments, size)],
                            chunk({}, "tool_calls")])

            self.reply = model
            async with self.proxy() as client:
                response = await client.post("/v1/chat/completions", json=body)

            self.assertNothingLeaked()
            deltas = [event["choices"][0]["delta"] for event in received_events(response)]
            self.assertEqual("".join(delta.get("content") or "" for delta in deltas), text, size)
            streamed = "".join(call["function"].get("arguments", "") for delta in deltas for call in delta.get("tool_calls", []))
            self.assertEqual(json.loads(streamed), json.loads(arguments), size)
            self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")


class AnthropicMessagesTest(ProxyCase):
    async def test_system_blocks_and_tool_inputs_are_masked_and_signed_thinking_is_left_alone(self):
        thinking = {"type": "thinking", "thinking": "o cliente [PESSOA_1] pediu", "signature": "sig"}
        body = {"model": "claude-sonnet", "max_tokens": 100,
                "system": [{"type": "text", "text": "Você atende Maria Souza.", "cache_control": {"type": "ephemeral"}}],
                "messages": [
                    {"role": "user", "content": "Meu CPF é 529.982.247-25"},
                    {"role": "assistant", "content": [thinking, {"type": "tool_use", "id": "tu_1", "name": "send_email", "input": {
                        "to": "maria@exemplo.com.br", "meta": {"names": ["Maria Souza"]}}}]},
                    {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": [{"type": "text", "text": "enviado para maria@exemplo.com.br"}]},
                        {"type": "text", "text": "Avise Maria Souza"}]},
                ]}

        def model(received):
            name = received["messages"][2]["content"][1]["text"].removeprefix("Avise ")
            to = received["messages"][1]["content"][1]["input"]["to"]
            return JSONResponse({"id": "msg_1", "type": "message", "role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "thinking", "thinking": f"devo avisar {name}", "signature": "s2"},
                {"type": "text", "text": f"Aviso enviado a {name}"},
                {"type": "tool_use", "id": "tu_2", "name": "send_email", "input": {"to": to, "note": f"para {name}"}}]})

        self.reply = model
        async with self.proxy() as client:
            response = await client.post("/v1/messages", json=body, headers={"x-api-key": "k", "anthropic-version": "2023-06-01"})
            self.reply = lambda received: JSONResponse({"content": []})
            await client.post("/v1/messages", json={"model": "claude-sonnet", "system": "Você atende Maria Souza.", "messages": []})

        self.assertNothingLeaked()
        sent = json.loads(self.seen[0]["raw"])
        self.assertEqual(self.seen[0]["headers"]["x-api-key"], "k")
        self.assertEqual(sent["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(sent["messages"][1]["content"][0], thinking)
        self.assertEqual((sent["messages"][1]["content"][1]["name"], sent["messages"][2]["content"][0]["tool_use_id"]), ("send_email", "tu_1"))
        content = response.json()["content"]
        self.assertEqual(content[0], {"type": "thinking", "thinking": "devo avisar [PESSOA_1]", "signature": "s2"})
        self.assertEqual(content[1]["text"], "Aviso enviado a Maria Souza")
        self.assertEqual(content[2]["input"], {"to": "maria@exemplo.com.br", "note": "para Maria Souza"})

    async def test_tokens_split_across_stream_events_are_restored(self):
        text = "Avise Maria Souza (maria@exemplo.com.br) fim ["
        tool_input = {"to": "maria@exemplo.com.br", "body": 'Maria Souza no Sítio "Boa Vista"\n'}
        body = {"model": "claude-sonnet", "stream": True, "messages": [
            {"role": "user", "content": text},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "tu_1", "name": "send_email", "input": tool_input}]}]}
        for size in range(1, 12):
            def model(received):
                delta = lambda index, kind, field, value: {"type": "content_block_delta", "index": index, "delta": {"type": kind, field: value}}
                masked_input = json.dumps(received["messages"][1]["content"][0]["input"], ensure_ascii=False)
                return sse([{"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "content": []}},
                            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
                            delta(0, "thinking_delta", "thinking", "cliente [PESSOA_1]"),
                            {"type": "content_block_stop", "index": 0},
                            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
                            *[delta(1, "text_delta", "text", piece) for piece in pieces(received["messages"][0]["content"], size)],
                            {"type": "content_block_stop", "index": 1},
                            {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu_2", "name": "send_email", "input": {}}},
                            *[delta(2, "input_json_delta", "partial_json", piece) for piece in pieces(masked_input, size)],
                            {"type": "content_block_stop", "index": 2},
                            {"type": "message_stop"}])

            self.reply = model
            async with self.proxy() as client:
                response = await client.post("/v1/messages", json=body)

            self.assertNothingLeaked()
            events = received_events(response)
            joined = lambda index, field: "".join(e["delta"][field] for e in events if e["type"] == "content_block_delta" and e["index"] == index)
            self.assertEqual(joined(0, "thinking"), "cliente [PESSOA_1]")
            self.assertEqual(joined(1, "text"), text, size)
            self.assertEqual(json.loads(joined(2, "partial_json")), tool_input, size)
            names = [line[7:] for line in response.text.splitlines() if line.startswith("event: ")]
            self.assertEqual(names, [event["type"] for event in events])
            self.assertEqual([names[0], names[-1]], ["message_start", "message_stop"])
            stops = [i for i, e in enumerate(events) if e["type"] == "content_block_stop"]
            self.assertTrue(all(e["index"] != events[stop]["index"] for stop in stops for e in events[stop + 1:] if "index" in e))


CHAT = {"model": "coordenacao", "messages": [{"role": "user", "content": "Maria Souza, CPF 529.982.247-25"}]}


def echo(received):
    return JSONResponse({"choices": [{"index": 0, "message": {"role": "assistant", "content": received["messages"][0]["content"]}}]})


class OperationTest(ProxyCase):
    async def test_shadow_mode_forwards_the_original_and_only_counts_what_it_would_mask(self):
        self.reply = echo
        with self.assertLogs("llm_mask_ptbr", "INFO") as logs:
            async with self.proxy(mode="shadow") as client:
                response = await client.post("/v1/chat/completions", json=CHAT)
                stats = (await client.get("/_mask/stats")).json()
        self.assertIn("Maria Souza, CPF 529.982.247-25", self.seen[0]["raw"])
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "Maria Souza, CPF 529.982.247-25")
        self.assertEqual(stats, {"mode": "shadow", "requests": 1, "found": {"PESSOA": 1, "CPF": 1}})
        entry = json.loads(logs.records[0].getMessage())
        self.assertEqual((entry["path"], entry["model"], entry["action"], entry["found"], entry["status"]),
                         ("/v1/chat/completions", "coordenacao", "shadow", {"PESSOA": 1, "CPF": 1}, 200))
        self.assertFalse(any(secret in record.getMessage() for record in logs.records for secret in SECRETS))

    async def test_models_served_at_home_get_the_original_text(self):
        self.reply = lambda received: JSONResponse({"choices": [{"index": 0, "message": {"role": "assistant", "content": "[PESSOA_1]"}}]})
        async with self.proxy(unmasked_models=["local"]) as client:
            await client.post("/v1/chat/completions", json=CHAT)
            response = await client.post("/v1/chat/completions", json={**CHAT, "model": "local"})
        self.assertNotIn("Maria Souza", self.seen[0]["raw"])
        self.assertIn("Maria Souza, CPF 529.982.247-25", self.seen[1]["raw"])
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "[PESSOA_1]")

    async def test_requests_it_cannot_inspect_are_refused_instead_of_forwarded(self):
        async with self.proxy() as client:
            unknown = await client.post("/v1/embeddings", json={"model": "m", "input": "Maria Souza"})
            broken = await client.post("/v1/chat/completions", content=b"Maria Souza")
            deleted = await client.delete("/v1/files/1")
        self.assertEqual((unknown.status_code, broken.status_code, deleted.status_code), (501, 400, 501))
        self.assertEqual(unknown.json()["error"]["type"], "llm_mask_ptbr")
        self.assertEqual(self.seen, [])

    async def test_get_requests_pass_through_with_their_query(self):
        self.reply = lambda received: JSONResponse({"data": [{"id": "coordenacao"}]})
        async with self.proxy() as client:
            response = await client.get("/v1/models?limit=5", headers={"Authorization": "Bearer k"})
        self.assertEqual((self.seen[0]["method"], self.seen[0]["path"], self.seen[0]["headers"]["authorization"]), ("GET", "/v1/models", "Bearer k"))
        self.assertEqual(response.json(), {"data": [{"id": "coordenacao"}]})

    async def test_provider_errors_keep_their_status_and_come_back_readable(self):
        self.reply = lambda received: JSONResponse({"error": {"message": "invalid: " + received["messages"][0]["content"]}}, 400)
        async with self.proxy() as client:
            rejected = await client.post("/v1/chat/completions", json=CHAT)
            self.reply = lambda received: PlainTextResponse("upstream busy", 503)
            busy = await client.post("/v1/chat/completions", json=CHAT)
        self.assertNothingLeaked()
        self.assertEqual((rejected.status_code, rejected.json()["error"]["message"]), (400, "invalid: Maria Souza, CPF 529.982.247-25"))
        self.assertEqual((busy.status_code, busy.text), (503, "upstream busy"))

    async def test_an_unreachable_provider_is_reported_as_a_bad_gateway(self):
        def refuse(request):
            raise httpx.ConnectError("connection refused")

        async with self.proxy(transport=httpx.MockTransport(refuse)) as client:
            response = await client.post("/v1/chat/completions", json=CHAT)
        self.assertEqual((response.status_code, response.json()["error"]["type"]), (502, "llm_mask_ptbr"))

    async def test_the_model_is_told_what_the_tokens_are(self):
        self.reply = lambda received: JSONResponse({})
        cached = {"type": "text", "text": "Regras.", "cache_control": {"type": "ephemeral"}}
        async with self.proxy(notice="AVISO", unmasked_models=["local"]) as client:
            await client.post("/v1/chat/completions", json=CHAT)
            await client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "system", "content": "Regras."}, *CHAT["messages"]]})
            await client.post("/v1/messages", json={"model": "m", "messages": CHAT["messages"]})
            await client.post("/v1/messages", json={"model": "m", "system": "Regras.", "messages": CHAT["messages"]})
            await client.post("/v1/messages", json={"model": "m", "system": [cached], "messages": CHAT["messages"]})
            await client.post("/v1/chat/completions", json={**CHAT, "model": "local"})
        sent = [json.loads(request["raw"]) for request in self.seen]
        self.assertEqual([m["role"] for m in sent[0]["messages"]], ["system", "user"])
        self.assertEqual(sent[0]["messages"][0]["content"], "AVISO")
        self.assertEqual(sent[1]["messages"][0], {"role": "system", "content": "Regras.\n\nAVISO"})
        self.assertEqual((sent[2]["system"], sent[3]["system"]), ("AVISO", "Regras.\n\nAVISO"))
        self.assertEqual(sent[4]["system"], [cached, {"type": "text", "text": "AVISO"}])
        self.assertEqual(sent[5], {**CHAT, "model": "local"})


if __name__ == "__main__":
    unittest.main()
