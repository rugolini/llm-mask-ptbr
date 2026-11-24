import json

# The provider signs these blocks; changing their text makes it reject the next request.
SIGNED = {"thinking", "redacted_thinking"}


def restore_all(node, fn):
    return _deep(node, fn)


def _deep(node, fn):
    if isinstance(node, str):
        return fn(node)
    if isinstance(node, list):
        return [_deep(item, fn) for item in node]
    if isinstance(node, dict):
        return {key: _deep(value, fn) for key, value in node.items()}
    return node


def _json_string(text, fn):
    try:
        return json.dumps(_deep(json.loads(text), fn), ensure_ascii=False)
    except ValueError:
        return fn(text)


def _content(content, fn, for_tool=None):
    if isinstance(content, str):
        return fn(content)
    if isinstance(content, list):
        return [_block(block, fn, for_tool) for block in content]
    return content


def _block(block, fn, for_tool=None):
    if not isinstance(block, dict):
        return block
    if block.get("type") in SIGNED:
        return block
    block = dict(block)
    if isinstance(block.get("text"), str):
        block["text"] = fn(block["text"])
    if "input" in block:
        block["input"] = _deep(block["input"], for_tool(block.get("name")) if for_tool else fn)
    if "content" in block:
        block["content"] = _content(block["content"], fn, for_tool)
    return block


def _message(message, fn, for_tool=None):
    message = dict(message)
    if "content" in message:
        message["content"] = _content(message["content"], fn, for_tool)
    if message.get("tool_calls"):
        message["tool_calls"] = [_tool_call(call, fn, for_tool) for call in message["tool_calls"]]
    return message


def _tool_call(call, fn, for_tool=None):
    call = dict(call)
    function = dict(call.get("function") or {})
    if isinstance(function.get("arguments"), str):
        function["arguments"] = _json_string(function["arguments"], for_tool(function.get("name")) if for_tool else fn)
    call["function"] = function
    return call


def transform_request(body, fn):
    body = dict(body)
    if "system" in body:
        body["system"] = _content(body["system"], fn)
    body["messages"] = [_message(message, fn) for message in body.get("messages", [])]
    return body


def transform_response(body, fn, for_tool=None):
    """for_tool(name) gives the function for that tool's arguments, where a secret may be restored; fn is for everything else."""
    body = dict(body)
    if isinstance(body.get("content"), list):
        body["content"] = _content(body["content"], fn, for_tool)
    if isinstance(body.get("choices"), list):
        body["choices"] = [{**choice, "message": _message(choice["message"], fn, for_tool)} if isinstance(choice.get("message"), dict)
                           else choice for choice in body["choices"]]
    return body


def add_notice(body, notice, anthropic):
    """Appends the notice to the system prompt, after any cached prefix, so the provider cache still hits."""
    body = dict(body)
    if anthropic:
        body["system"] = _appended(body.get("system"), notice)
        return body
    messages = list(body.get("messages", []))
    if messages and messages[0].get("role") in ("system", "developer"):
        messages[0] = {**messages[0], "content": _appended(messages[0].get("content"), notice)}
    else:
        messages.insert(0, {"role": "system", "content": notice})
    body["messages"] = messages
    return body


def _appended(content, notice):
    if isinstance(content, list):
        return [*content, {"type": "text", "text": notice}]
    return f"{content}\n\n{notice}" if content else notice
