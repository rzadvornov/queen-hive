"""Route one hive session's API calls: the provider's models to its API, local models to their own server.

Each CLI sends every request to a single address. When some bees run on a local model, the hive points the
CLI at this router on localhost. Requests for the provider's models pass through unchanged, login headers
included; requests for a local model go to its server (Ollama, llama.cpp, LM Studio …) without them:
- Claude Code (ANTHROPIC_BASE_URL): the server's Anthropic API, as is.
- Codex (a custom model provider): the server's OpenAI Responses API, as is.
- Gemini CLI (GOOGLE_GEMINI_BASE_URL): the server's chat completions, translated (hive.translate).
"""

import json
import os
import re
import socket
import threading

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

ANTHROPIC = "https://api.anthropic.com"
HOP_BY_HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade",
              "proxy-authorization", "proxy-connection", "te", "trailer"}
SECRETS = {"authorization", "x-api-key", "cookie", "chatgpt-account-id", "x-goog-api-key", "openai-organization",
           "openai-project"}
GEMINI_PATH = re.compile(r"/models/(.+):(\w+)$")   # /v1beta/models/<model>:streamGenerateContent


def upstream_for(provider: str) -> str:
    """Where the provider's own requests go."""
    if provider == "gemini":
        return os.environ.get("GOOGLE_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com"
    if provider == "gpt":
        from hive import codex

        return codex.upstream()
    return os.environ.get("ANTHROPIC_BASE_URL") or ANTHROPIC


def create_app(local: dict[str, str], upstream: str = ANTHROPIC, provider: str = "claude", reader: str | None = None) -> Starlette:
    """local: model ID → base URL of the server that runs it. reader (Codex): the provider's model that reads the
    Queen's encrypted messages out for a local bee."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30))
    decoded: dict[str, str] = {}

    async def route(request: Request) -> Response:
        body = await request.body()
        model, path = None, request.url.path
        if provider == "gemini":
            found = GEMINI_PATH.search(path)
            model = found.group(1) if found else None
        elif body and request.method == "POST":
            try:
                model = json.loads(body).get("model")
            except (ValueError, AttributeError):
                model = None
        base = local.get(model) if model else None
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        if base:
            if provider == "gemini":
                return await gemini_local(client, base, model, found.group(2), body)
            if path.endswith(("/count_tokens", "/responses/input_tokens")):   # not every local server has it
                return JSONResponse({"input_tokens": max(1, len(body) // 4)})
            headers = {k: v for k, v in headers.items() if k.lower() not in SECRETS}
            headers["x-api-key"] = "local"
            if provider == "gpt":   # Codex asks for <base_url>/responses; the server's OpenAI API is under /v1
                path = "/v1" + path
                if path.endswith("/responses"):
                    body = json.dumps(await codex_local(json.loads(body), dict(request.headers), client, upstream,
                                                        reader, decoded)).encode()
        target = (base or upstream).rstrip("/") + path + (f"?{request.url.query}" if request.url.query else "")
        upstream_request = client.build_request(request.method, target, headers=headers, content=body)
        try:
            response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as error:
            where = f"local model server {base}" if base else upstream
            return JSONResponse({"type": "error", "error": {"type": "api_error", "message": f"hive router: {where} "
                                                            f"unreachable ({type(error).__name__})"}}, status_code=502)
        passed = {k: v for k, v in response.headers.items() if k.lower() not in HOP_BY_HOP}

        async def chunks():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(chunks(), status_code=response.status_code, headers=passed)

    return Starlette(routes=[Route("/{path:path}", route, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])])


CODEX_ITEMS = {"message", "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output",
               "local_shell_call", "local_shell_call_output", "reasoning"}
READ_OUT = ("Repeat the text of the task message below exactly, word for word, and nothing else: no comments, no "
            "quotes, no formatting of your own.")


async def codex_local(body: dict, headers: dict, client: httpx.AsyncClient, upstream: str, reader: str | None,
                      decoded: dict[str, str]) -> dict:
    """A Codex bee's request for a local model, made plain: messages between agents become user messages, with the
    Queen's encrypted text read out by the provider's own model (once per message), and the items and tools that only
    OpenAI's servers know are left out."""
    if not isinstance(body.get("input"), list):   # a plain text input
        return body
    items = []
    for item in body["input"]:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "agent_message":
            parts = []
            for part in item.get("content") or []:
                if part.get("type") == "encrypted_content":
                    blob = part.get("encrypted_content") or ""
                    if blob not in decoded:
                        decoded[blob] = await read_out(item, part, headers, client, upstream, reader)
                    parts.append(decoded[blob])
                else:
                    parts.append(part.get("text") or "")
            items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "".join(parts)}]})
        elif kind in CODEX_ITEMS and not (kind == "reasoning" and item.get("encrypted_content")):
            items.append(item)
    plain = {k: v for k, v in body.items() if k not in ("include", "client_metadata", "prompt_cache_key", "store")}
    return {**plain, "input": items, "tools": [t for t in body.get("tools") or [] if t.get("type") == "function"]}


async def read_out(item: dict, part: dict, headers: dict, client: httpx.AsyncClient, upstream: str,
                   reader: str | None) -> str:
    """The text of an encrypted message: only the provider's servers can decrypt it, so one of its models repeats it."""
    if not reader:
        return "(the Queen's message is encrypted and no model was set to read it)"
    request = {"model": reader, "stream": True, "store": False, "instructions": READ_OUT,
               "input": [{**item, "content": [part]}], "tools": []}
    passed = {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP and k.lower() != "accept-encoding"}
    text = []
    try:
        async with client.stream("POST", upstream.rstrip("/") + "/responses", json=request, headers=passed) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[6:])
                    except ValueError:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        text.append(event.get("delta") or "")
    except httpx.HTTPError as error:
        return f"(the Queen's message couldn't be read: {type(error).__name__})"
    return "".join(text) or "(the Queen's message couldn't be read)"


async def gemini_local(client: httpx.AsyncClient, base: str, model: str, method: str, body: bytes) -> Response:
    """A Gemini API call answered by a local model's chat completions."""
    from hive import translate

    try:
        request = json.loads(body or b"{}")
    except ValueError:
        request = {}
    if method == "countTokens":
        return JSONResponse({"totalTokens": max(1, len(body) // 4)})
    try:
        answer = await client.post(base.rstrip("/") + "/v1/chat/completions", json=translate.to_openai(request, model),
                                   headers={"authorization": "Bearer local"})
    except httpx.HTTPError as error:
        return JSONResponse({"error": {"code": 502, "status": "UNAVAILABLE", "message": f"hive router: local model "
                                       f"server {base} unreachable ({type(error).__name__})"}}, status_code=502)
    if answer.status_code != 200:
        return JSONResponse({"error": {"code": answer.status_code, "status": "INTERNAL",
                                       "message": f"local model server: {answer.text[:500]}"}}, status_code=answer.status_code)
    reply = translate.to_gemini(answer.json(), model, translate.declared(request))
    if method == "streamGenerateContent":   # the whole answer as one event
        return Response(f"data: {json.dumps(reply, ensure_ascii=False)}\r\n\r\n", media_type="text/event-stream")
    return JSONResponse(reply)


class Router:
    """The router on a free localhost port, in a background thread, for the length of a session."""

    def __init__(self, local: dict[str, str], upstream: str | None = None, provider: str = "claude",
                 reader: str | None = None):
        import uvicorn

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        app = create_app(local, upstream or upstream_for(provider), provider, reader)
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def __enter__(self) -> "Router":
        self.thread.start()
        for _ in range(100):   # Claude Code's first request must find it listening
            if self.server.started:
                break
            threading.Event().wait(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
