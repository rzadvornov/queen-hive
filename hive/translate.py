"""Gemini API ⇄ OpenAI chat completions, so a Gemini CLI bee can run on a local model (Ollama, llama.cpp, LM Studio …).

Local servers speak the Anthropic and OpenAI APIs but not Gemini's. The router hands a bee's Gemini request to
`to_openai`, sends it to the local server's /v1/chat/completions, and turns the answer back with `to_gemini`.
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
