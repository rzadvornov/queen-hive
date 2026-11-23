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


def test_codex_local_bees_reach_the_servers_responses_api():
    request = lambda url, model: httpx.post(url + "/responses", json={"model": model, "input": "hi"},
                                            headers={"authorization": "Bearer chatgpt", "chatgpt-account-id": "acct"},
                                            timeout=10).json()
    with Serve(fake("openai")) as cloud, Serve(fake("local")) as local:
        with Router({"qwen2.5-coder:14b": local.url}, upstream=cloud.url, provider="gpt") as router:
            gpt = request(router.url, "gpt-6-luna")
            assert gpt["who"] == "openai" and gpt["path"] == "/responses" and gpt["authorization"] == "Bearer chatgpt"
            qwen = request(router.url, "qwen2.5-coder:14b")
            assert qwen["who"] == "local" and qwen["path"] == "/v1/responses" and qwen["authorization"] is None


def test_gemini_local_bees_are_translated_to_chat_completions():
    seen = {}

    async def completions(request):
        seen.update(await request.json(), path=request.url.path, key=request.headers.get("x-goog-api-key"))
        return JSONResponse({"choices": [{"finish_reason": "tool_calls", "message": {"content": "Reading it.", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 7}})

    body = {"systemInstruction": {"parts": [{"text": "You are a scout."}]},
            "contents": [{"role": "user", "parts": [{"text": "Find the bug"}]},
                         {"role": "model", "parts": [{"text": "hmm", "thought": True},
                                                     {"functionCall": {"name": "glob", "args": {"pattern": "*.py"}}}]},
                         {"role": "user", "parts": [{"functionResponse": {"name": "glob", "response": {"output": "a.py"}}}]}],
            "tools": [{"functionDeclarations": [
                {"name": "glob", "parametersJsonSchema": {"type": "object", "properties": {"pattern": {"type": "string"}}}},
                {"name": "read_file", "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"}}}}]}],
            "generationConfig": {"temperature": 1, "thinkingConfig": {"thinkingLevel": "HIGH"}}}
    local = Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"])])
    with Serve(fake("google", stream=True)) as cloud, Serve(local) as server:
        with Router({"qwen2.5-coder:14b": server.url}, upstream=cloud.url, provider="gemini") as router:
            path = "/v1beta/models/{}:streamGenerateContent?alt=sse"
            gemini = httpx.post(router.url + path.format("gemini-3.5-flash-lite"), json=body,
                                headers={"x-goog-api-key": "secret"}, timeout=10)
            assert '"who": "google"' in gemini.text                                       # Gemini passes through
            reply = httpx.post(router.url + path.format("qwen2.5-coder:14b"), json=body,
                               headers={"x-goog-api-key": "secret"}, timeout=10)
    assert seen["path"] == "/v1/chat/completions" and seen["key"] is None and seen["model"] == "qwen2.5-coder:14b"
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "tool"]
    call = seen["messages"][2]["tool_calls"][0]
    assert seen["messages"][2]["content"] is None                                         # thoughts are left out
    assert seen["messages"][3]["tool_call_id"] == call["id"] and json.loads(call["function"]["arguments"]) == {"pattern": "*.py"}
    assert seen["tools"][1]["function"]["parameters"]["properties"]["path"]["type"] == "string"
    event = json.loads(reply.text.strip()[len("data: "):])
    parts = event["candidates"][0]["content"]["parts"]
    assert parts[0] == {"text": "Reading it."} and parts[1]["functionCall"] == {"id": "c1", "name": "read_file", "args": {"path": "a.py"}}
    assert event["usageMetadata"]["promptTokenCount"] == 50

    from hive import translate

    plain = {"choices": [{"message": {"content": "add: fine. mean: off by one."}}]}
    finished = translate.to_gemini(plain, "qwen", translate.declared(
        {"tools": [{"functionDeclarations": [{"name": "read_file"}, {"name": "complete_task"}]}]}))
    assert finished["candidates"][0]["content"]["parts"] == [   # a sub-agent's plain last answer ends its task
        {"functionCall": {"id": "finish", "name": "complete_task", "args": {"result": "add: fine. mean: off by one."}}}]
    assert translate.to_gemini(plain, "qwen")["candidates"][0]["content"]["parts"] == [{"text": "add: fine. mean: off by one."}]


def test_local_bees_for_every_provider(hive_home):
    from hive import cli

    models.add_local("qwen-coder", "qwen2.5-coder:14b")
    for provider in ("claude", "gpt", "gemini"):
        assert cli._of_provider("qwen-coder", provider, "--scout").local


def test_codex_local_bees_get_the_queens_encrypted_message_read_out():
    asked = []

    async def responses(request):
        body = await request.json()
        asked.append((body, request.headers.get("authorization")))
        if body["model"] == "gpt-6-luna":   # the reader, on the provider's servers
            async def events():
                for piece in ("Read calc.py ", "and report."):
                    yield f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': piece})}\n\n".encode()
            return StreamingResponse(events(), media_type="text/event-stream")
        return JSONResponse(body)

    app = Starlette(routes=[Route("/{path:path}", responses, methods=["POST"])])
    brief = {"type": "agent_message", "author": "/root", "content": [
        {"type": "input_text", "text": "Payload:\n"}, {"type": "encrypted_content", "encrypted_content": "gAAA"}]}
    body = {"model": "qwen2.5-coder:14b", "include": ["reasoning.encrypted_content"], "input": [
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are a scout."}]},
        {"type": "additional_tools", "tools": []}, brief, brief],
        "tools": [{"type": "function", "name": "exec_command"}, {"type": "namespace", "name": "mcp__apps", "tools": []}]}
    with Serve(app) as cloud, Serve(app) as local:
        with Router({"qwen2.5-coder:14b": local.url}, upstream=cloud.url, provider="gpt", reader="gpt-6-luna") as router:
            sent = httpx.post(router.url + "/responses", json=body, headers={"authorization": "Bearer chatgpt"},
                              timeout=10).json()
    assert [b["model"] for b, _ in asked] == ["gpt-6-luna", "qwen2.5-coder:14b"]   # read out once, then cached
    assert asked[0][1] == "Bearer chatgpt" and asked[1][1] is None
    assert [i["type"] for i in sent["input"]] == ["message", "message", "message"]
    assert sent["input"][1]["content"][0]["text"] == "Payload:\nRead calc.py and report."
    assert [t["name"] for t in sent["tools"]] == ["exec_command"] and "include" not in sent
