"""Translations to OpenAI chat completions, for custom models whose endpoint has no API the CLI speaks.

- Gemini API ⇄ chat completions (`to_openai`, `to_gemini`): Gemini CLI bees on any custom model.
- Anthropic Messages ⇄ chat completions (`anthropic_to_openai`, `openai_to_anthropic`, `anthropic_events`): Claude
  Code on an endpoint with only an OpenAI API (llama.cpp, vLLM, Groq, Together …).

Each answer is fetched whole and handed back in the CLI's own format, as one stream when it asked for one.
"""

import json

SKIP_CONFIG = {"thinkingConfig", "responseModalities"}
FINISH_TOOL = "complete_task"   # a Gemini CLI sub-agent ends by calling it with its result


def _schema(schema):
    """A Gemini `parameters` schema (OpenAPI, types in capitals) as JSON Schema; `parametersJsonSchema` already is."""
    if isinstance(schema, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _schema(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_schema(v) for v in schema]
    return schema


def _text(parts: list[dict]) -> str:
    return "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))


def to_openai(body: dict, model: str) -> dict:
    messages = []
    system = _text((body.get("systemInstruction") or {}).get("parts") or [])
    if system:
        messages.append({"role": "system", "content": system})
    calls = []   # ids of the calls not yet answered, in order: a functionResponse may come without its id
    for turn, content in enumerate(body.get("contents") or []):
        parts = content.get("parts") or []
        if content.get("role") == "model":
            tool_calls = []
            for i, part in enumerate(p for p in parts if "functionCall" in p):
                call = part["functionCall"]
                call_id = call.get("id") or f"call_{turn}_{i}"
                calls.append(call_id)
                tool_calls.append({"id": call_id, "type": "function", "function": {
                    "name": call.get("name", ""), "arguments": json.dumps(call.get("args") or {})}})
            message = {"role": "assistant", "content": _text(parts) or None}
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)
            continue
        for part in parts:
            if "functionResponse" in part:
                answer = part["functionResponse"]
                call_id = answer.get("id") or (calls[0] if calls else answer.get("name", "call"))
                if call_id in calls:
                    calls.remove(call_id)
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps(answer.get("response"), ensure_ascii=False)})
        text = _text(parts)
        if text:
            messages.append({"role": "user", "content": text})
    request = {"model": model, "messages": messages, "stream": False}
    tools = [{"type": "function", "function": {
        "name": f["name"], "description": f.get("description", ""),
        "parameters": f.get("parametersJsonSchema") or _schema(f.get("parameters")) or {"type": "object", "properties": {}}}}
        for group in body.get("tools") or [] for f in group.get("functionDeclarations") or []]
    if tools:
        request["tools"] = tools
    config = {k: v for k, v in (body.get("generationConfig") or {}).items() if k not in SKIP_CONFIG}
    for ours, theirs in (("temperature", "temperature"), ("topP", "top_p"), ("maxOutputTokens", "max_tokens")):
        if ours in config:
            request[theirs] = config[ours]
    return request


FINISH = {"stop": "STOP", "tool_calls": "STOP", "length": "MAX_TOKENS", "content_filter": "SAFETY"}


def declared(body: dict) -> set[str]:
    return {f.get("name") for group in body.get("tools") or [] for f in group.get("functionDeclarations") or []}


def to_gemini(answer: dict, model: str, tools: set[str] = frozenset()) -> dict:
    """The answer as a Gemini response. tools: the functions the request declared. Local models often end a
    sub-agent's work with a plain answer instead of calling complete_task, so that answer becomes the call."""
    choice = (answer.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    if FINISH_TOOL in tools and message.get("content") and not message.get("tool_calls"):
        message = {"tool_calls": [{"id": "finish", "function": {"name": FINISH_TOOL,
                                                                "arguments": json.dumps({"result": message["content"]})}}]}
    parts = [{"text": message["content"]}] if message.get("content") else []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except ValueError:
            args = {}
        parts.append({"functionCall": {"id": call.get("id"), "name": function.get("name", ""),
                                       "args": args if isinstance(args, dict) else {}}})
    usage = answer.get("usage") or {}
    prompt, completion = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    return {"candidates": [{"content": {"role": "model", "parts": parts or [{"text": ""}]}, "index": 0,
                            "finishReason": FINISH.get(choice.get("finish_reason"), "STOP")}],
            "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": completion,
                              "totalTokenCount": prompt + completion},
            "modelVersion": model}


# --- Anthropic Messages ⇄ OpenAI chat completions: Claude Code on an endpoint with only an OpenAI API ---------------

def _blocks(content) -> list[dict]:
    return [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]


def _image(block: dict) -> dict | None:
    source = block.get("source") or {}
    if source.get("type") == "base64":
        return {"type": "image_url", "image_url": {"url": f"data:{source.get('media_type')};base64,{source.get('data')}"}}
    if source.get("type") == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url")}}
    return None


def _user_content(blocks: list[dict]):
    """Text, or text and image parts when there are images."""
    parts = [{"type": "text", "text": b.get("text", "")} if b.get("type") == "text" else _image(b)
             for b in blocks if b.get("type") in ("text", "image")]
    parts = [p for p in parts if p]
    if all(p["type"] == "text" for p in parts):
        return "\n".join(p["text"] for p in parts)
    return parts


def _result_text(content) -> str:
    return content if isinstance(content, str) else "\n".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def anthropic_to_openai(body: dict, model: str) -> dict:
    messages = []
    system = _result_text(body.get("system")) if body.get("system") else ""
    if system:
        messages.append({"role": "system", "content": system})
    for message in body.get("messages") or []:
        blocks = _blocks(message.get("content"))
        if message.get("role") == "assistant":
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            calls = [{"id": b.get("id"), "type": "function", "function": {
                "name": b.get("name", ""), "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                for b in blocks if b.get("type") == "tool_use"]
            entry = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            messages.append(entry)
            continue
        for block in blocks:   # tool results first: they answer the previous assistant turn
            if block.get("type") == "tool_result":
                text = _result_text(block.get("content"))
                messages.append({"role": "tool", "tool_call_id": block.get("tool_use_id"),
                                 "content": ("Error: " + text) if block.get("is_error") else text})
        rest = [b for b in blocks if b.get("type") in ("text", "image")]
        if rest:
            messages.append({"role": "user", "content": _user_content(rest)})
    request = {"model": model, "messages": messages, "stream": False}
    tools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
             for t in body.get("tools") or [] if isinstance(t, dict) and t.get("name") and t.get("type") in (None, "custom")]
    if tools:
        request["tools"] = tools
        choice = body.get("tool_choice") or {}
        if choice.get("type") == "any":
            request["tool_choice"] = "required"
        elif choice.get("type") == "tool":
            request["tool_choice"] = {"type": "function", "function": {"name": choice.get("name")}}
        elif choice.get("type") == "none":
            request["tool_choice"] = "none"
    for ours, theirs in (("max_tokens", "max_tokens"), ("temperature", "temperature"), ("top_p", "top_p"),
                         ("stop_sequences", "stop")):
        if body.get(ours) is not None:
            request[theirs] = body[ours]
    return request


STOP = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens", "content_filter": "end_turn"}


def openai_to_anthropic(answer: dict, model: str) -> dict:
    choice = (answer.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        content.append({"type": "tool_use", "id": call.get("id") or f"toolu_{len(content)}", "name": function.get("name", ""),
                        "input": arguments if isinstance(arguments, dict) else {}})
    usage = answer.get("usage") or {}
    reason = "tool_use" if message.get("tool_calls") else STOP.get(choice.get("finish_reason"), "end_turn")
    return {"id": answer.get("id") or "msg_hive", "type": "message", "role": "assistant", "model": model,
            "content": content or [{"type": "text", "text": ""}], "stop_reason": reason, "stop_sequence": None,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}}


def anthropic_events(message: dict) -> str:
    """A whole message as the event stream Claude Code reads."""
    def event(kind: str, data: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **data}, ensure_ascii=False)}\n\n"

    start = {**message, "content": [], "stop_reason": None, "usage": {**message["usage"], "output_tokens": 0}}
    out = [event("message_start", {"message": start})]
    for index, block in enumerate(message["content"]):
        if block["type"] == "tool_use":
            out.append(event("content_block_start", {"index": index, "content_block": {**block, "input": {}}}))
            out.append(event("content_block_delta", {"index": index, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}}))
        else:
            out.append(event("content_block_start", {"index": index, "content_block": {"type": "text", "text": ""}}))
            out.append(event("content_block_delta", {"index": index, "delta": {"type": "text_delta", "text": block["text"]}}))
        out.append(event("content_block_stop", {"index": index}))
    out.append(event("message_delta", {"delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
                                       "usage": {"output_tokens": message["usage"]["output_tokens"]}}))
    out.append(event("message_stop", {}))
    return "".join(out)
