import asyncio
import json

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from hive import folders, init
from hive.modes import Policy


def test_folders_in_goal(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "notes.md").write_text("x")
    goal = f'port utils from {tmp_path}/a to "{tmp_path}/b/notes.md", ratio a/b, missing /nope/x'
    assert folders.folders_in(goal) == [(tmp_path / "a").resolve(), (tmp_path / "b").resolve()]
    assert folders.folders_in("no folders here, just a/b") == []
    assert folders.resolve("nothing", [], tmp_path) == [tmp_path.resolve()]


def test_start_point_without_git(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.txt").write_text("1")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    start = folders.start_point(root, run_dir)
    assert start.commit is None and start.manifest.exists()
    import changes

    (root / "a.txt").write_text("22")
    (root / "b.txt").write_text("new")
    diff = changes.diff(root, start.manifest)
    assert diff == {"added": ["b.txt"], "modified": ["a.txt"], "deleted": []}


def test_detect_stacks(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node --test", "start": "node s.js"}}))
    (tmp_path / "go.mod").write_text("module x")
    (tmp_path / "acceptance").mkdir()
    found = init.detect(tmp_path)
    assert found["stacks"][0].startswith("JavaScript") and "Go" in found["stacks"]
    assert found["commands"]["test"] == "npm test" and found["commands"]["run"] == "npm start"
    assert found["commands"]["build"] == "go build ./..."
    assert found["protected"] == ["acceptance/"]
    profile = init.heuristic_profile(tmp_path, found)
    assert "- test: `npm test`" in profile and "- acceptance/" in profile


def test_policy_tools_by_mode(tmp_path):
    auto = Policy("auto", [tmp_path], {"test": "npm test"})
    ask = Policy("ask", [tmp_path], {"test": "npm test"})
    plan = Policy("plan", [tmp_path])
    assert "Bash" in auto.allowed_tools and auto.permission_mode == "acceptEdits"
    assert "Edit" not in auto.allowed_tools      # outside-folder edits must reach can_use_tool
    assert "Bash" not in ask.allowed_tools and "Bash(npm test)" in ask.allowed_tools
    assert plan.permission_mode == "plan"


def test_policy_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr("hive.ui.interactive", lambda: False)
    auto = Policy("auto", [tmp_path])
    inside = asyncio.run(auto.can_use_tool("Write", {"file_path": str(tmp_path / "x")}, None))
    outside = asyncio.run(auto.can_use_tool("Write", {"file_path": "/etc/hosts"}, None))
    assert isinstance(inside, PermissionResultAllow)
    assert isinstance(outside, PermissionResultDeny)
    ask = Policy("ask", [tmp_path])
    bash = asyncio.run(ask.can_use_tool("Bash", {"command": "curl x"}, None))
    assert isinstance(bash, PermissionResultDeny)          # nobody at the keyboard to approve
    plan = asyncio.run(Policy("plan", [tmp_path]).can_use_tool("ExitPlanMode", {"plan": "p"}, None))
    assert isinstance(plan, PermissionResultDeny) and plan.interrupt


def test_waggle_runs_after_a_job(tmp_path, monkeypatch):
    import hive.chat
    import hive.session
    from hive import cli, ui

    calls = []
    monkeypatch.setattr(hive.session, "run_job", lambda job: _record("sess-1"))
    monkeypatch.setattr(hive.chat, "chat", lambda job, prompt, resume=None: calls.append((prompt, resume)) or _noop())
    monkeypatch.setattr(ui, "interactive", lambda: True)
    base = ["goal", "-d", str(tmp_path), "--queen", "sonnet-5.5", "--workers", "haiku-5.5", "--mode", "auto", "--no-init"]

    with pytest.raises(SystemExit):
        cli.cmd_run(base)
    assert calls == [("/haiku-hive:waggle", "sess-1")]             # resumes the job's own session

    with pytest.raises(SystemExit):
        cli.cmd_run([*base, "--no-waggle"])
    monkeypatch.setattr(ui, "interactive", lambda: False)
    with pytest.raises(SystemExit):
        cli.cmd_run(base)
    assert len(calls) == 1                                          # off by flag, and without a terminal


def _record(session_id):
    async def run():
        return {"session_id": session_id, "acceptance": {"passed": True}, "status": "done"}
    return run()


async def _noop():
    return None


def test_settings_confirm_then_configure(tmp_path, monkeypatch):
    import argparse

    from hive import cli, memory, models, ui

    def args(**kw):
        return argparse.Namespace(dir=[tmp_path], no_init=True, **{"queen": None, "workers": None, "mode": None, **kw})

    asked, picks = [], {}
    monkeypatch.setattr(ui, "confirm", lambda q, default=True: asked.append(q) or picks["confirm"])
    monkeypatch.setattr(ui, "choose", lambda title, options, default=None: next((v for k, v in picks.items() if k in title), default))

    picks["confirm"] = True                                          # yes: last choices, else the defaults
    _, queen, workers, mode = cli._choose(args())
    assert (queen.key, workers.key, mode) == (models.DEFAULT_QUEEN, models.DEFAULT_WORKERS, "plan")
    assert "Claude Opus 5.5" in asked[-1] and "Claude Haiku 5.5" in asked[-1]

    picks.update({"confirm": False, "Queen": "sonnet-5.5", "bee model": "sonnet-5.5", "mode": "auto"})   # no: configure each
    _, queen, workers, mode = cli._choose(args())
    assert (queen.key, workers.key, mode) == ("sonnet-5.5", "sonnet-5.5", "auto")
    assert memory.load_state()["workers"] == "sonnet-5.5"           # remembered as the new defaults

    n = len(asked)
    cli._choose(args(queen="opus-5.5", workers="haiku-5.5", mode="ask"))
    assert len(asked) == n                                           # everything given: nothing asked


def test_ask_folder(tmp_path, monkeypatch):
    from hive import memory, ui

    known, other = tmp_path / "api", tmp_path / "shop"
    known.mkdir()
    other.mkdir()
    memory.ensure_project(known)
    monkeypatch.setattr(ui, "interactive", lambda: True)
    answers = iter(["1", "", str(tmp_path / "missing"), str(other)])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert folders.known_projects() == [known.resolve()]
    assert folders.ask_folder(tmp_path) == known.resolve()          # a known project by number
    assert folders.ask_folder(tmp_path) == tmp_path.resolve()       # Enter keeps the default
    assert folders.ask_folder(tmp_path) == other.resolve()          # not a folder: asks again, then a path
    monkeypatch.setattr(ui, "interactive", lambda: False)
    assert folders.ask_folder(tmp_path) == tmp_path.resolve()       # no terminal: no question


def test_waggle_does_not_loop(tmp_path, monkeypatch):
    import hive.chat
    from hive import models
    from hive.session import Job

    prompts = []

    async def converse(client, prompt, tracker):           # the Queen ends every turn with a hive-summary block
        prompts.append(prompt)
        tracker.last_queen_text = 'Done.\n```hive-summary\n{"status": "done"}\n```'

    monkeypatch.setattr(hive.chat, "converse", converse)
    job = Job(goal="", folders=[tmp_path], queen=models.get("sonnet-5.5"), workers=models.get("haiku-5.5"), mode="auto")
    session = hive.chat.ChatSession(job)

    asyncio.run(session.turn("add a feature"))
    assert prompts == ["add a feature", "/haiku-hive:waggle"]      # one retro after the job, then back to the user
    asyncio.run(session.turn("apply 1"))
    assert prompts[-1] == "apply 1" and len(prompts) == 3          # applying the retro's edits starts no new retro
    asyncio.run(session.turn("next goal"))
    assert prompts[-2:] == ["next goal", "/haiku-hive:waggle"]     # the next real job gets its retro
