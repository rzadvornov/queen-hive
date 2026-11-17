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
    base = ["goal", "-d", str(tmp_path), "--queen", "sonnet-5.5", "--mode", "auto", "--no-init"]

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
