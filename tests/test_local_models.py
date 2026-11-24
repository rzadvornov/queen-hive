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
    assert {k: m.base_url for k, m in job.local_models().items()} == {"qwen2.5-coder:14b": models.OLLAMA_URL}


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
            assert seen["who"] == "local" and seen["authorization"] == "Bearer local" and seen["x-api-key"] == "local"   # no login leaks

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
            assert qwen["who"] == "local" and qwen["path"] == "/v1/responses" and qwen["authorization"] == "Bearer local"


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
    assert asked[0][1] == "Bearer chatgpt" and asked[1][1] == "Bearer local"
    assert [i["type"] for i in sent["input"]] == ["message", "message", "message"]
    assert sent["input"][1]["content"][0]["text"] == "Payload:\nRead calc.py and report."
    assert [t["name"] for t in sent["tools"]] == ["exec_command"] and "include" not in sent


def test_custom_models_from_presets_and_older_entries(hive_home, monkeypatch):
    models.local_path().parent.mkdir(parents=True, exist_ok=True)
    models.local_path().write_text(json.dumps({"local": [{"key": "old", "id": "qwen2.5-coder:14b",
                                                          "base_url": "http://box:11434"}]}))
    old = models.get("old")   # an entry from before custom models: one server with both APIs
    assert old.anthropic_url == old.openai_url == "http://box:11434" and not old.queen_effort

    routed = models.add_local("or-qwen", "qwen/qwen3-coder", via="openrouter", queen=True, price=(0.3, 1.2, 0.0))
    assert routed.anthropic_url == routed.openai_url == "https://openrouter.ai/api" and routed.key_env == "OPENROUTER_API_KEY"
    assert routed.queen_effort == models.CUSTOM_QUEEN and models.coordinating_effort(routed) is None   # no --effort sent
    assert routed in models.queens("claude") and (routed.input, routed.output) == (0.3, 1.2)
    groq = models.add_local("groq-llama", "llama-3.3-70b", via="groq")
    assert groq.anthropic_url is None and groq.openai_url == "https://api.groq.com/openai"
    mine = models.add_local("mine", "m", openai_url="https://host/api/", key_env="MY_KEY")
    assert mine.anthropic_url is None and mine.openai_url == "https://host/api" and mine.key_env == "MY_KEY"
    saved = json.loads(models.local_path().read_text())
    assert "local" not in saved and [e["key"] for e in saved["custom"]] == ["old", "or-qwen", "groq-llama", "mine"]
    assert "price" in saved["custom"][1] and saved["custom"][1]["queen"] is True

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("MY_KEY", "k")
    assert models.missing_keys([routed, mine, old]) == ["OPENROUTER_API_KEY"]
    with pytest.raises(SystemExit):
        models.add_local("x", "y", via="nowhere")


def test_custom_queen_rules(tmp_path, hive_home, monkeypatch):
    from hive import cli, launch

    models.add_local("or-qwen", "qwen/qwen3-coder", via="openrouter", queen=True)
    models.add_local("bee-only", "qwen2.5-coder:14b")
    monkeypatch.setattr(launch, "run", lambda job, headless=False: seen.append(job) or [])
    seen = []
    base = ["x", "--headless", "-d", str(tmp_path), "--no-init", "--mode", "auto"]
    for argv, error in ((["--queen", "or-qwen", "--provider", "gpt"], "runs in Claude Code"),
                        (["--queen", "bee-only"], "--queen"),
                        (["--queen", "or-qwen", "--workers", "haiku-5.5", "--compare", "sonnet-5.5", "--yes"], "--compare")):
        with pytest.raises(SystemExit, match=error):
            cli.cmd_run(base + argv)
    with pytest.raises(SystemExit):
        cli.cmd_run(base + ["--queen", "or-qwen", "--workers", "bee-only"])
    job = seen[-1]
    assert job.provider == "claude" and set(job.local_models()) == {"qwen/qwen3-coder", "qwen2.5-coder:14b"}
    assert "You run on a custom model" in launch.queen_prompt(job, hive_home, None)
    env = launch.no_claude_env(job.queen)
    assert env["ANTHROPIC_SMALL_FAST_MODEL"] == "qwen/qwen3-coder" and env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_anthropic_requests_translated_for_an_openai_only_endpoint(monkeypatch):
    from hive import translate

    seen = {}

    async def completions(request):
        seen.update(await request.json(), path=request.url.path, auth=request.headers.get("authorization"))
        return JSONResponse({"choices": [{"finish_reason": "tool_calls", "message": {"content": "Reading.", "tool_calls": [
            {"id": "c2", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "a.py"}'}}]}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 6}})

    body = {"model": "llama-3.3-70b", "stream": True, "max_tokens": 512,
            "system": [{"type": "text", "text": "You are the Queen."}],
            "tools": [{"name": "Read", "description": "read", "input_schema": {"type": "object"}},
                      {"type": "web_search_20250305", "name": "web_search"}],
            "messages": [{"role": "user", "content": "Fix it"},
                         {"role": "assistant", "content": [{"type": "thinking", "thinking": "hm"},
                                                           {"type": "tool_use", "id": "c1", "name": "Glob", "input": {"pattern": "*"}}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "a.py"},
                                                      {"type": "text", "text": "go on"}]}]}
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq")
    groq = lambda url: models.Model("groq", "llama-3.3-70b", "Llama", 0, 0, 0, base_url=url, openai_url=url,
                                    key_env="GROQ_API_KEY")
    local = Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"])])
    with Serve(fake("anthropic")) as cloud, Serve(local) as server:
        with Router({"llama-3.3-70b": groq(server.url)}, upstream=cloud.url) as router:
            reply = httpx.post(router.url + "/v1/messages?beta=true", json=body,
                               headers={"authorization": "Bearer my-login"}, timeout=10)
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer secret-groq"   # its key, not my login
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "tool", "user"]
    assert seen["messages"][2]["tool_calls"][0]["id"] == "c1" and seen["messages"][3]["tool_call_id"] == "c1"
    assert [t["function"]["name"] for t in seen["tools"]] == ["Read"] and seen["max_tokens"] == 512
    events = [line[len("event: "):] for line in reply.text.splitlines() if line.startswith("event: ")]
    assert events == ["message_start", "content_block_start", "content_block_delta", "content_block_stop",
                      "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"]
    data = [json.loads(line[6:]) for line in reply.text.splitlines() if line.startswith("data: ")]
    assert data[4]["content_block"]["name"] == "Read" and json.loads(data[5]["delta"]["partial_json"]) == {"file_path": "a.py"}
    assert data[7]["delta"]["stop_reason"] == "tool_use"
    plain = translate.openai_to_anthropic({"choices": [{"finish_reason": "stop", "message": {"content": "Done."}}]}, "m")
    assert plain["content"] == [{"type": "text", "text": "Done."}] and plain["stop_reason"] == "end_turn"


def test_custom_anthropic_endpoint_gets_its_own_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    routed = lambda url: models.Model("or", "qwen/qwen3-coder", "Qwen", 0, 0, 0, base_url=url, anthropic_url=url,
                                      openai_url=url, key_env="OPENROUTER_API_KEY")
    with Serve(fake("anthropic")) as cloud, Serve(fake("openrouter")) as server:
        with Router({"qwen/qwen3-coder": routed(server.url)}, upstream=cloud.url) as router:
            got = httpx.post(router.url + "/v1/messages", json={"model": "qwen/qwen3-coder", "messages": []},
                             headers={"authorization": "Bearer my-login"}, timeout=10).json()
    assert got["who"] == "openrouter" and got["path"] == "/v1/messages"
    assert got["authorization"] == "Bearer sk-or" and got["x-api-key"] == "sk-or"
