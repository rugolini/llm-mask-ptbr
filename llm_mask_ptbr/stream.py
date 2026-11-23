import json

from .engine import PARTIAL_TOKEN


def _json_escaped(value):
    return json.dumps(value, ensure_ascii=False)[1:-1]


class StreamRestorer:
    """Restores tokens in a server-sent event stream, holding back a token that is cut between two events."""

    def __init__(self, masker):
        self.masker = masker
        self.buffer = b""
        self.held = {}
        self.kinds = {}

    def feed(self, chunk):
        *events, self.buffer = (self.buffer + chunk).replace(b"\r\n", b"\n").split(b"\n\n")
        return b"".join(self._event(event.decode()) for event in events)

    def close(self):
        rest, self.buffer = self.buffer, b""
        return rest

    def _event(self, event):
        lines, flushed = event.split("\n"), []
        for i, line in enumerate(lines):
            if not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[5:])
            except ValueError:
                continue
            if isinstance(data, dict):
                flushed += self._restore(data)
                lines[i] = "data: " + json.dumps(data, ensure_ascii=False)
        before = "".join(f"event: {extra['type']}\ndata: {json.dumps(extra, ensure_ascii=False)}\n\n" for extra in flushed)
        return (before + "\n".join(lines) + "\n\n").encode()

    def _restore(self, data):
        """Restores the event in place; returns events that must be sent before it."""
        self._openai(data)
        return self._anthropic(data)

    def _anthropic(self, data):
        key = ("block", data.get("index"))
        if data.get("type") == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                delta["text"] = self._push(key, delta["text"])
            elif delta.get("type") == "input_json_delta":
                delta["partial_json"] = self._push(key, delta["partial_json"], _json_escaped)
            if key in self.held:
                self.kinds[key] = delta.get("type")
        elif data.get("type") == "content_block_stop" and key in self.held:
            kind = self.kinds.pop(key)
            field = "text" if kind == "text_delta" else "partial_json"
            return [{"type": "content_block_delta", "index": key[1], "delta": {"type": kind, field: self.held.pop(key)}}]
        return []

    def _openai(self, data):
        for choice in data.get("choices") or []:
            index = choice.get("index", 0)
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice["delta"] = {}
            if isinstance(delta.get("content"), str):
                delta["content"] = self._push(("content", index), delta["content"])
            for call in delta.get("tool_calls") or []:
                function = call.get("function") or {}
                if isinstance(function.get("arguments"), str):
                    function["arguments"] = self._push(("call", index, call.get("index", 0)), function["arguments"], _json_escaped)
            if choice.get("finish_reason"):
                for key in [key for key in self.held if key[1] == index]:
                    rest = self.held.pop(key)
                    if key[0] == "content":
                        delta["content"] = (delta.get("content") or "") + rest
                    else:
                        delta.setdefault("tool_calls", []).append({"index": key[2], "function": {"arguments": rest}})

    def _push(self, key, text, escape=lambda value: value):
        text = self.held.pop(key, "") + text
        partial = PARTIAL_TOKEN.search(text)
        if partial:
            self.held[key] = text[partial.start():]
            text = text[:partial.start()]
        return self.masker.restore(text, escape)
