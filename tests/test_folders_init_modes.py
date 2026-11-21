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


def test_tilde_paths_are_expanded(tmp_path, monkeypatch):
    from pathlib import Path

    from hive import memory

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop" / "app").mkdir(parents=True)
    real = tmp_path / "Desktop" / "app"
    assert memory.project_dir("~/Desktop/app") == memory.project_dir(real)      # same project either way
    assert folders.resolve("", [Path("~/Desktop/app")], tmp_path) == [real.resolve()]
    pdir = asyncio.run(init.run(Path("~/Desktop/app"), use_ai=False))
    assert pdir == memory.project_dir(real) and not memory.profile_is_blank(pdir)
