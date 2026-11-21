"""Route one hive session's API calls: Claude models to Anthropic, local models to their own server.

Claude Code sends every request to a single address (ANTHROPIC_BASE_URL). When some bees run on a
local model, the hive points Claude Code at this router on localhost. Requests for Claude models pass
through unchanged, login headers included; requests for a local model go to its Anthropic-compatible
server (Ollama, llama.cpp, LM Studio …) without the login headers.
"""

import json
import os
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
SECRETS = {"authorization", "x-api-key", "cookie"}


def create_app(local: dict[str, str], upstream: str = ANTHROPIC) -> Starlette:
    """local: model ID → base URL of the server that runs it."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30))

    async def route(request: Request) -> Response:
        body = await request.body()
        model = None
        if body and request.method == "POST":
            try:
                model = json.loads(body).get("model")
            except (ValueError, AttributeError):
                model = None
        base = local.get(model) if model else None
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        if base:
            if request.url.path.endswith("/count_tokens"):   # not every local server has it; a rough count is enough
                return JSONResponse({"input_tokens": max(1, len(body) // 4)})
            headers = {k: v for k, v in headers.items() if k.lower() not in SECRETS}
            headers["x-api-key"] = "local"
        target = (base or upstream).rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
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


class Router:
    """The router on a free localhost port, in a background thread, for the length of a session."""

    def __init__(self, local: dict[str, str], upstream: str | None = None):
        import uvicorn

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        app = create_app(local, upstream or os.environ.get("ANTHROPIC_BASE_URL") or ANTHROPIC)
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
