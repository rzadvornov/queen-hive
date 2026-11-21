import json
import os
import subprocess
import sys
import textwrap

import pytest

from hive import SCRIPTS_DIR, memory, models, portable, providers, stats

SUMMARY = '```hive-summary\n{"done_when": ["test -f hello.txt"], "status": "done"}\n```'


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """A folder on PATH for fake `codex` and `gemini` executables."""
    folder = tmp_path / "bin"
    folder.mkdir()
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")

    def install(name: str, body: str):
        script = folder / name
        script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
        script.chmod(0o755)
        return script

    return install


def test_provider_is_asked_once_then_remembered(monkeypatch):
    from hive import ui

    asked = []
    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(ui, "choose", lambda title, options, default=None: asked.append(title) or "gemini")
    assert providers.current() == "gemini"
    assert providers.current() == "gemini" and len(asked) == 1        # saved: not asked again
    assert providers.current("gpt") == "gpt"                          # --provider: this run only
    assert providers.saved() == "gemini"
    providers.save("claude")                                          # `hive provider claude`
    assert providers.current() == "claude" and len(asked) == 1


def test_without_a_terminal_claude_is_used_and_nothing_saved(monkeypatch):
    from hive import ui

    monkeypatch.setattr(ui, "interactive", lambda: False)
    assert providers.current() == "claude"
    assert providers.saved() is None
    assert providers.get("openai").key == "gpt" and providers.get("Google").key == "gemini"


def test_hive_provider_command(capsys, monkeypatch):
    from hive import cli, ui

    monkeypatch.setattr(ui, "interactive", lambda: False)
    cli.cmd_provider(["gpt"])
    assert providers.saved() == "gpt"
    assert "GPT (Codex CLI)" in capsys.readouterr().out
    cli.cmd_provider([])
    assert "❯ gpt" in capsys.readouterr().out


def test_models_are_remembered_per_provider():
    state = {}
    assert [m.key for m in models.remembered(state, "gpt")] == ["gpt-5.5", "gpt-5.4-mini"]
    assert [m.key for m in models.remembered(state, "gemini")] == ["gemini-3.1-pro", "gemini-3-flash"]
    models.remember(state, models.get("gpt-5.4"), models.get("gpt-5.4-mini"))
    models.remember(state, models.get("sonnet-5.5"), models.get("haiku-5.5"))
    assert models.remembered(state, "gpt")[0].key == "gpt-5.4"
    assert models.remembered(state, "claude")[0].key == "sonnet-5.5"
    assert state["last_queen"] == "sonnet-5.5"                        # where older versions look
    assert {m.provider for m in models.queens("gemini")} == {"gemini"}
    assert all(m.provider == "claude" for m in models.queens())


def test_price_overrides(hive_home):
    hive_home.mkdir(parents=True, exist_ok=True)
    (hive_home / "models.json").write_text(json.dumps({"prices": {"gpt-5.5": {"input": 1, "output": 2}}}))
    model = models.get("gpt-5.5")
    assert (model.input, model.output, model.cache_read) == (1.0, 2.0, 0.5)
    models.add_local("qwen", "qwen:7b")                               # adding a local model keeps the prices
    assert json.loads((hive_home / "models.json").read_text())["prices"]


def test_choose_keeps_models_within_the_provider(tmp_path, fake_bin, monkeypatch):
    import argparse

    from hive import cli, ui

    fake_bin("codex", "print('codex 1.0')")
    monkeypatch.setattr(ui, "confirm", lambda q, default=True: True)

    def args(**kw):
        return argparse.Namespace(dir=[tmp_path], no_init=True, **{"queen": None, "workers": None, "mode": None,
                                                                    "provider": None, **kw})

    _, queen, workers, _ = cli._choose(args(queen="gpt-5.4"))          # the Queen's provider, without asking
    assert (queen.key, workers.key) == ("gpt-5.4", "gpt-5.4-mini")
    with pytest.raises(SystemExit, match="is a Claude model"):
        cli._choose(args(provider="gpt", workers="haiku-5.5"))
    providers.save("gemini")
    which = providers.shutil.which
    monkeypatch.setattr(providers.shutil, "which", lambda name: None if name == "gemini" else which(name))
    with pytest.raises(SystemExit, match="Gemini CLI not found"):
        cli._choose(args())


def test_rules_for_other_providers():
    claude, gpt, gemini = (portable.rules_for(p) for p in ("claude", "gpt", "gemini"))
    assert "haiku-hive:scout" in claude and "spawn_agent" not in claude
    assert "spawn_agent" in gpt and "`agent_type`" in gpt and "haiku-hive" not in gpt and "Haiku" not in gpt
    assert "invoke_agent" in gemini and "haiku-hive" not in gemini
    for rules in (gpt, gemini):
        assert "- S = scout" in rules and "## Brief template" in rules and "hive-summary" in rules


def job_for(tmp_path, queen, workers, **kw):
    from hive.job import Job

    return Job(goal="write hello", folders=[tmp_path], queen=models.get(queen), workers=models.get(workers), mode="auto",
               **kw)


def test_codex_command_and_home(tmp_path, fake_bin, monkeypatch, hive_home):
    from hive import codex

    fake_bin("codex", "")
    user = tmp_path / "user-codex"
    user.mkdir()
    (user / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(user))
    pdir = memory.ensure_project(tmp_path)
    job = job_for(tmp_path, "gpt-5.5", "gpt-5.4-mini", roles={"scout": models.get("gpt-5.4")})
    argv, env = codex.command(job, pdir, "QUEEN RULES", "id", headless=True)

    assert argv[1:4] == ["exec", "--json", "--skip-git-repo-check"]
    assert argv[argv.index("--cd") + 1] == str(tmp_path) and argv[argv.index("--add-dir") + 1] == str(pdir)
    assert 'developer_instructions="QUEEN RULES"' in argv and 'approval_policy="never"' in argv
    assert argv[-2:] == ["--", "write hello"]
    root = hive_home / "codex"
    assert env == {"CODEX_HOME": str(root)}
    assert (root / "auth.json").resolve() == (user / "auth.json").resolve()
    scout = (root / "agents" / "scout.toml").read_text()
    assert 'model = "gpt-5.4"' in scout and 'sandbox_mode = "read-only"' in scout
    assert 'model = "gpt-5.4-mini"' in (root / "agents" / "builder.toml").read_text()
    hooks = json.loads((root / "hooks.json").read_text())["hooks"]
    assert "protect.py" in hooks["PreToolUse"][0]["hooks"][0]["command"]
    skill = (root / "skills" / "review" / "SKILL.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}" not in skill and "haiku-hive:" not in skill


def test_gemini_command_and_home(tmp_path, fake_bin, monkeypatch, hive_home):
    from hive import gemini

    fake_bin("gemini", "")
    user = tmp_path / "user"
    (user / ".gemini").mkdir(parents=True)
    (user / ".gemini" / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}},
                                                                 "hooks": {"BeforeTool": [{"matcher": "x", "hooks": []}]}}))
    (user / ".gemini" / "oauth_creds.json").write_text("{}")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(user))
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    pdir = memory.ensure_project(tmp_path)
    argv, env = gemini.command(job_for(tmp_path, "gemini-3.1-pro", "gemini-3-flash"), pdir, "QUEEN RULES", "sid", False)

    assert argv[argv.index("--session-id") + 1] == "sid" and argv[argv.index("--approval-mode") + 1] == "yolo"
    assert argv[-2:] == ["--prompt-interactive", "write hello"]
    root = hive_home / "gemini" / ".gemini"
    assert env == {"GEMINI_CLI_HOME": str(hive_home / "gemini")}
    assert (root / "GEMINI.md").read_text() == "QUEEN RULES"
    settings = json.loads((root / "settings.json").read_text())
    assert settings["security"]["auth"]["selectedType"] == "gemini-api-key"
    assert settings["hooks"]["BeforeTool"][0]["matcher"] == "x"           # yours are kept
    assert "protect.py" in settings["hooks"]["BeforeTool"][1]["hooks"][0]["command"]
    scout = (root / "agents" / "scout.md").read_text()
    assert "model: gemini-3-flash-preview" in scout and "write_file" not in scout and "kind: local" in scout
    assert (root / "oauth_creds.json").is_symlink()


def rollout_lines(meta: dict, *items) -> str:
    stamp = "2030-01-01T10:00:{:02d}Z"
    lines = [{"timestamp": stamp.format(0), "type": "session_meta", "payload": meta}]
    lines += [{"timestamp": stamp.format(i + 1), "type": kind, "payload": payload} for i, (kind, payload) in enumerate(items)]
    return "".join(json.dumps(line) + "\n" for line in lines)


def tokens(input_tokens, cached, output):
    return ("event_msg", {"type": "token_count", "info": {"total_token_usage": {
        "input_tokens": input_tokens, "cached_input_tokens": cached, "output_tokens": output}}})


CODEX_FAKE = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
cwd = args[args.index("--cd") + 1]
Path(cwd, "hello.txt").write_text("hi")
day = Path(os.environ["CODEX_HOME"], "sessions", "2030", "01", "01")
day.mkdir(parents=True, exist_ok=True)
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def write(name, meta, items):
    lines = [{"timestamp": now, "type": "session_meta", "payload": meta}]
    lines += [{"timestamp": now, "type": k, "payload": p} for k, p in items]
    Path(day, name).write_text("".join(json.dumps(l) + "\n" for l in lines))
def count(i, c, o):
    return ("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o}}})
write("rollout-main.jsonl", {"id": "main-1", "session_id": "main-1", "cwd": cwd, "source": "exec", "timestamp": now}, [
    ("turn_context", {"model": "gpt-5.5"}),
    ("event_msg", {"type": "user_message", "message": args[-1]}),
    count(1000, 200, 100), count(1000, 200, 100),
    ("response_item", {"type": "function_call", "name": "spawn_agent", "call_id": "c1",
                       "arguments": json.dumps({"message": "B1 write hello\nGoal: ...", "agent_type": "builder", "task_name": "b1"})}),
    ("response_item", {"type": "function_call_output", "call_id": "c1", "output": "agent finished"}),
    ("response_item", {"type": "function_call", "name": "exec_command", "call_id": "c2", "arguments": json.dumps({"cmd": "cat hello.txt"})}),
    ("response_item", {"type": "function_call_output", "call_id": "c2", "output": json.dumps({"output": "hi", "metadata": {"exit_code": 0}})}),
    count(3000, 1200, 300),
    ("event_msg", {"type": "agent_message", "message": "Done.\n" + SUMMARY}),
])
write("rollout-bee.jsonl", {"id": "bee-1", "session_id": "main-1", "parent_thread_id": "main-1", "agent_role": "builder",
                            "source": {"subagent": {}}, "cwd": cwd, "timestamp": now}, [
    ("turn_context", {"model": "gpt-5.4-mini"}),
    ("event_msg", {"type": "user_message", "message": "B1 write hello\nGoal: ..."}),
    count(5000, 0, 400),
])
print(json.dumps({"type": "thread.started", "thread_id": "main-1"}))
print(json.dumps({"type": "turn.completed", "usage": {}}))
'''.replace("SUMMARY", repr(SUMMARY))


def test_headless_run_in_codex(tmp_path, fake_bin, monkeypatch, capsys):
    from hive import cli

    fake_bin("codex", CODEX_FAKE)
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.raises(SystemExit) as done:
        cli.cmd_run(["write hello", "--headless", "--provider", "gpt", "-d", str(project), "--no-init", "--mode", "auto",
                     "--queen", "gpt-5.5", "--workers", "gpt-5.4-mini"])
    assert done.value.code == 0, capsys.readouterr().out
    record = stats.load_runs(memory.all_projects())[-1]
    assert record["provider"] == "gpt" and record["queen"]["key"] == "gpt-5.5"
    assert record["acceptance"]["passed"] is True                       # the Queen's done_when ran here
    assert [b["label"] for b in record["hive"]["briefs"]] == ["B1"]
    assert record["hive"]["checks"] == [{"command": "cat hello.txt", "ok": True}]
    stages = record["hive"]["by_stage"]
    assert stages["queen"]["tokens"] == {"input": 1800, "output": 300, "cache_read": 1200, "cache_write": 0}
    assert stages["build"]["tokens"]["input"] == 5000                   # the bee's own rollout
    assert set(record["hive"]["by_model"]) == {"gpt-5.5", "gpt-5.4-mini"}
    assert record["hive"]["cost_usd"] > 0
    assert [e["model"] for e in record["estimates"]] == ["gpt-5.5", "gpt-5.4", "gpt-5.3-codex"]


GEMINI_FAKE = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
sid = args[args.index("--session-id") + 1]
chats = Path(os.environ["GEMINI_CLI_HOME"], ".gemini", "tmp", "proj", "chats")
(chats / sid).mkdir(parents=True, exist_ok=True)
Path("hello.txt").write_text("hi")
def write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
t = "2030-01-01T10:00:00Z"
reply = {"id": "m2", "type": "gemini", "timestamp": t, "content": "", "model": "gemini-3.1-pro-preview",
         "toolCalls": [{"id": "t1", "name": "invoke_agent", "args": {"agent_name": "builder", "prompt": "B1 write hello\nGoal"},
                        "status": "success"},
                       {"id": "t2", "name": "run_shell_command", "args": {"command": "false"}, "status": "success",
                        "result": [{"functionResponse": {"response": {"output": "Exit Code: 1"}}}]}]}
write(chats / f"session-2030-01-01T10-00-{sid[:8]}.jsonl", [
    {"sessionId": sid, "projectHash": "p", "startTime": t, "kind": "main"},
    {"id": "m1", "type": "user", "timestamp": t, "content": [{"text": args[args.index("--prompt") + 1]}]},
    reply,
    {**reply, "tokens": {"input": 1000, "output": 50, "cached": 400, "thoughts": 20, "total": 1070}},
    {"id": "m3", "type": "gemini", "timestamp": t, "content": "Done.\n" + SUMMARY, "model": "gemini-3.1-pro-preview",
     "tokens": {"input": 2000, "output": 80, "cached": 0, "thoughts": 0, "total": 2080}},
])
write(chats / sid / "bee.jsonl", [
    {"sessionId": "bee", "kind": "subagent"},
    {"id": "b1", "type": "user", "timestamp": t, "content": "B1 write hello\nGoal"},
    {"id": "b2", "type": "gemini", "timestamp": t, "content": "ok", "model": "gemini-3-flash-preview",
     "tokens": {"input": 700, "output": 30, "cached": 0, "thoughts": 0, "total": 730}},
])
print(json.dumps({"session_id": sid, "response": "Done.", "stats": {}}, indent=2))
'''.replace("SUMMARY", repr(SUMMARY))


def test_headless_run_in_gemini(tmp_path, fake_bin, capsys):
    from hive import cli

    fake_bin("gemini", GEMINI_FAKE)
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.raises(SystemExit) as done:
        cli.cmd_run(["write hello", "--headless", "--provider", "gemini", "-d", str(project), "--no-init",
                     "--mode", "auto", "--queen", "gemini-3.1-pro", "--workers", "gemini-3-flash"])
    assert done.value.code == 0, capsys.readouterr().out
    record = stats.load_runs(memory.all_projects())[-1]
    assert record["provider"] == "gemini"
    assert record["hive"]["briefs"][0]["label"] == "B1" and record["hive"]["briefs"][0]["stage"] == "build"
    assert record["hive"]["checks"] == [{"command": "false", "ok": False}]   # "Exit Code: 1" in the result
    stages = record["hive"]["by_stage"]
    assert stages["queen"]["tokens"] == {"input": 2600, "output": 150, "cache_read": 400, "cache_write": 0}
    assert stages["build"]["tokens"]["input"] == 700
    assert record["acceptance"]["passed"] is True


def test_codex_rollout_ignores_repeated_totals(tmp_path):
    from hive import codex

    entries = [json.loads(line) for line in rollout_lines(
        {"id": "x", "cwd": str(tmp_path)}, ("turn_context", {"model": "gpt-5.5"}),
        tokens(100, 0, 10), tokens(100, 0, 10), ("event_msg", {"type": "token_count", "info": None}), tokens(250, 50, 30),
    ).splitlines()]
    usage = [(e["model"], e["tokens"].input, e["tokens"].cache_read, e["tokens"].output)
             for e in codex.events(entries) if e["t"] == "usage"]
    assert usage == [("gpt-5.5", 100, 0, 10), ("gpt-5.5", 100, 50, 20)]


def message(role, text):
    kind = "output_text" if role == "assistant" else "input_text"
    return ("response_item", {"type": "message", "role": role, "content": [{"type": kind, "text": text}]})


def test_codex_rollouts_without_user_message_events(hive_home):
    """Codex 0.171 logs prompts and replies only as messages, and a bee's brief arrives encrypted."""
    from hive import codex

    day = hive_home / "codex" / "sessions" / "2030" / "01" / "01"
    day.mkdir(parents=True)
    cwd = hive_home.parent / "proj"
    (day / "rollout-main.jsonl").write_text(rollout_lines(
        {"id": "main-1", "session_id": "main-1", "cwd": str(cwd), "source": "exec"},
        ("turn_context", {"model": "gpt-6-luna"}),
        message("developer", "# You are the Queen"),
        message("user", "<environment_context>\n  <cwd>x</cwd>"),
        message("user", "count lines"),
        ("response_item", {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration", "call_id": "c1",
                           "arguments": json.dumps({"task_name": "s1_count", "agent_type": "scout",
                                                    "message": "S1 count lines\nGoal: ..."})}),
        ("response_item", {"type": "function_call_output", "call_id": "c1", "output": '{"task_name":"/root/s1_count"}'}),
        tokens(1000, 0, 50),
        message("assistant", "5 lines."),
    ))
    (day / "rollout-bee.jsonl").write_text(rollout_lines(
        {"id": "bee-1", "session_id": "main-1", "parent_thread_id": "main-1", "agent_role": "scout",
         "agent_path": "/root/s1_count", "source": {"subagent": {}}, "cwd": str(cwd)},
        message("user", "count lines"),   # the Queen's history, copied when the bee was forked
        ("response_item", {"type": "agent_message", "author": "/root", "content": [
            {"type": "input_text", "text": "Message Type: NEW_TASK\nTask name: /root/s1_count\n"},
            {"type": "encrypted_content", "encrypted_content": "gAAAA"}]}),
        tokens(700, 0, 20),
    ))
    traces, exact, main_id = codex.transcript("ignored", 0, cwd)
    assert main_id == "main-1" and exact is None and len(traces) == 1
    assert traces[0].prompt == "count lines"
    events = codex.events([json.loads(line) for line in (day / "rollout-main.jsonl").read_text().splitlines()])
    assert [e["t"] for e in events] == ["prompt", "dispatch", "dispatched", "usage", "text"]
    assert events[1]["task"] == "s1_count"


def test_models_from_the_codex_account(hive_home, monkeypatch):
    """A ChatGPT plan offers its own models: they join the catalog and become the defaults."""
    from hive import models

    (hive_home / "codex").mkdir(parents=True)
    (hive_home / "codex" / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-hidden", "visibility": "hide", "priority": 1},
        {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list", "priority": 2},
        {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list", "priority": 3},
    ]}))
    keys = [m.key for m in models.catalog("gpt")]
    assert "gpt-6-luna" in keys and "gpt-5.6-terra" in keys and "gpt-hidden" not in keys
    assert [m.key for m in models.defaults("gpt")] == ["gpt-6-luna", "gpt-6-luna"]
    assert models.default_compare("gpt") == []   # catalog models aren't offered; offered ones have no price


def run_hook(script: str, payload: dict, env: dict | None = None) -> str:
    return subprocess.run([sys.executable, str(SCRIPTS_DIR / script)], input=json.dumps(payload), capture_output=True,
                          text=True, env={**os.environ, **(env or {})}).stdout


def test_protect_hook_in_codex_and_gemini(tmp_path):
    from test_memory_and_protection import write_profile

    write_profile(tmp_path, ["acceptance/"])
    patch = "*** Begin Patch\n*** Update File: acceptance/a.test.js\n@@\n-x\n+y\n*** End Patch"
    codex = run_hook("protect.py", {"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "cwd": str(tmp_path),
                                    "tool_input": {"command": patch}})
    assert json.loads(codex)["hookSpecificOutput"]["permissionDecision"] == "deny"
    scout = run_hook("protect.py", {"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "cwd": str(tmp_path),
                                    "agent_type": "scout", "tool_input": {"command": patch.replace("acceptance/", "src/")}})
    assert "read-only" in json.loads(scout)["hookSpecificOutput"]["permissionDecisionReason"]
    gemini = run_hook("protect.py", {"hook_event_name": "BeforeTool", "tool_name": "write_file", "cwd": str(tmp_path),
                                     "tool_input": {"file_path": "acceptance/b.js", "content": ""}})
    assert json.loads(gemini)["decision"] == "deny"
    shell = run_hook("protect.py", {"hook_event_name": "BeforeTool", "tool_name": "run_shell_command", "cwd": str(tmp_path),
                                    "tool_input": {"command": "echo x > acceptance/c.js"}})
    assert json.loads(shell)["decision"] == "deny"
    allowed = run_hook("protect.py", {"hook_event_name": "BeforeTool", "tool_name": "replace", "cwd": str(tmp_path),
                                      "tool_input": {"file_path": "src/app.js"}})
    assert allowed == ""


def test_events_hook_translates_gemini(tmp_path):
    chats = tmp_path / "chats"
    events = []

    def send(payload):
        run_hook("events.py", {"transcript_path": str(chats / "session-x.jsonl"), **payload}, {"HIVE_RUN_DIR": str(tmp_path)})

    send({"hook_event_name": "BeforeTool", "tool_name": "invoke_agent",
          "tool_input": {"agent_name": "scout", "prompt": "S1 find the auth code\nGoal: ..."}})
    send({"hook_event_name": "AfterTool", "tool_name": "invoke_agent",
          "tool_input": {"agent_name": "scout", "prompt": "S1 find the auth code"}, "tool_response": {"llmContent": "auth.py:3"}})
    send({"hook_event_name": "AfterTool", "tool_name": "run_shell_command", "tool_input": {"command": "npm test"},
          "tool_response": {"llmContent": "1 failed\nExit Code: 1"}})
    send({"hook_event_name": "AfterAgent", "prompt_response": "All done."})
    run_hook("events.py", {"hook_event_name": "AfterTool", "tool_name": "run_shell_command",   # a bee's own command
                           "transcript_path": str(chats / "sid" / "bee.jsonl"), "tool_input": {"command": "ls"},
                           "tool_response": {"llmContent": "x"}}, {"HIVE_RUN_DIR": str(tmp_path)})
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in events] == ["dispatch", "report", "check", "queen_text"]
    assert events[0]["label"] == "S1" and events[0]["stage"] == "scout" and events[0]["agent"] == "scout"
    assert events[1]["label"] == "S1" and events[1]["text"] == "auth.py:3"
    assert events[2]["ok"] is False and events[3]["text"] == "All done."


def test_gemini_records_skip_injected_context_and_rewinds(tmp_path):
    from hive import gemini

    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [
        {"sessionId": "s", "kind": "main"},
        {"id": "ctx", "type": "user", "content": [{"text": "<session_context>\nThis is the Gemini CLI."}]},
        {"id": "u1", "type": "user", "content": [{"text": "first try"}]},
        {"$rewindTo": "u1"},                                              # the failed turn is taken back
        {"id": "u2", "type": "user", "content": [{"text": "fix the bug"}]},
        {"$set": {"lastUpdated": "x"}},
    ]))
    assert gemini.events(gemini._records(path)[1]) == [{"t": "prompt", "text": "fix the bug", "ts": None}]
