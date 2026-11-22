import json
import socket
import threading

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from hive import CORE_DIR, models
from hive.router import Router
from hive.job import Job, plugin_for


class Serve:
    """A Starlette app on a free localhost port, for the length of a with-block."""

    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            threading.Event().wait(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


def fake(who: str, stream: bool = False):
    async def handler(request):
        seen = {"who": who, "path": request.url.path, "authorization": request.headers.get("authorization"),
                "x-api-key": request.headers.get("x-api-key"), "model": (await request.json()).get("model")}
        if stream:
            async def events():
                yield b"event: message_start\ndata: {}\n\n"
                yield ("data: " + json.dumps(seen) + "\n\n").encode()
            return StreamingResponse(events(), media_type="text/event-stream")
        return JSONResponse(seen)
    return Starlette(routes=[Route("/{path:path}", handler, methods=["POST"])])


def test_local_models_catalog(hive_home):
    assert models.local_models() == []
    added = models.add_local("qwen-coder", "qwen2.5-coder:14b")
    assert added.local and added.base_url == models.OLLAMA_URL and added.input == added.output == 0
    assert models.get("qwen-coder") == added == models.get("qwen2.5-coder:14b")
    from hive import pricing
    from hive.pricing import Tokens
    assert pricing.cost_by_id(Tokens(input=10**6, output=10**6), "qwen2.5-coder:14b") == 0   # local tokens are free
    with pytest.raises(SystemExit):
        models.add_local("opus-5.5", "x")                    # can't shadow a Claude model
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(SystemExit):
            models.add_local(bad, "x")                       # the key becomes part of a folder name
    assert models.remove_local("qwen-coder") and not models.remove_local("qwen-coder")
    with pytest.raises(KeyError):
        models.get("qwen-coder")


def test_per_bee_models(tmp_path, hive_home):
    haiku, sonnet = models.get("haiku-5.5"), models.get("sonnet-5.5")
    local = models.add_local("qwen-coder", "qwen2.5-coder:14b")
    job = Job(goal="", folders=[tmp_path], queen=models.get("opus-5.5"), workers=haiku, mode="auto")
    assert plugin_for(job.bee_models()) == CORE_DIR and job.local_models() == {}

    job.roles = {"scout": local, "builder": sonnet}
    plugin = plugin_for(job.bee_models())
    model_of = lambda bee: next(l for l in (plugin / "agents" / f"{bee}.md").read_text().splitlines() if l.startswith("model:"))
    assert model_of("scout") == "model: qwen2.5-coder:14b" and model_of("builder") == "model: claude-sonnet-5-5"
    assert model_of("reviewer") == "model: claude-haiku-5-5"
    assert job.local_models() == {"qwen2.5-coder:14b": models.OLLAMA_URL}


def test_router_splits_claude_and_local_traffic():
    request = lambda url, model, path="/v1/messages": httpx.post(
        url + path, json={"model": model, "messages": []},
        headers={"authorization": "Bearer my-login", "anthropic-version": "2023-06-01"}, timeout=10)
    with Serve(fake("anthropic")) as cloud, Serve(fake("local", stream=True)) as local:
        with Router({"qwen2.5-coder:14b": local.url}, upstream=cloud.url) as router:
            claude = request(router.url, "claude-haiku-5-5").json()
            assert claude["who"] == "anthropic" and claude["authorization"] == "Bearer my-login"   # login passes through

            streamed = request(router.url, "qwen2.5-coder:14b")
            assert streamed.headers["content-type"].startswith("text/event-stream")
            seen = json.loads(streamed.text.strip().splitlines()[-1][len("data: "):])
            assert seen["who"] == "local" and seen["authorization"] is None and seen["x-api-key"] == "local"   # no login leaks

            counted = request(router.url, "qwen2.5-coder:14b", "/v1/messages/count_tokens").json()
            assert counted["input_tokens"] > 0
    with Router({"qwen2.5-coder:14b": "http://127.0.0.1:9"}, upstream="http://127.0.0.1:9") as router:
        down = request(router.url, "qwen2.5-coder:14b")
        assert down.status_code == 502 and "unreachable" in down.json()["error"]["message"]
