"""Real side-by-side runs: the same goal done by one model alone, in a copy of the folder."""

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from hive import SCRIPTS_DIR, claude, memory, models, verify
from hive.pricing import Tokens

SOLO_PROMPT = """You are working alone on this task: no helpers or subagents.
Do the whole job yourself, then verify it by running the acceptance command(s) below until they pass.
Never change the protected paths listed below.
Reply in the user's language."""

SOLO_TOOLS = ["Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "TodoWrite"]
PROTECT_HOOK = {"hooks": {"PreToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [
    {"type": "command", "command": f'python3 "{SCRIPTS_DIR / "protect.py"}"'}]}]}}

GIT_ID = ["-c", "user.name=hive", "-c", "user.email=hive@localhost", "-c", "commit.gpgsign=false"]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *GIT_ID, *args], capture_output=True, text=True)


def prepare(target: Path, run_dir: Path, keys: list[str]) -> dict[str, Path]:
    """Copy the folder once per model, before the hive touches it, and commit the copy as a baseline."""
    base = memory.hive_home() / "tmp" / run_dir.name
    workspaces = {}
    for key in keys:
        ws = base / key
        shutil.copytree(target, ws, symlinks=True)
        if not (ws / ".git").exists():
            _git(ws, "init", "-q")
        _git(ws, "add", "-A")
        _git(ws, "commit", "-q", "--no-verify", "--allow-empty", "-m", "hive compare baseline")
        workspaces[key] = ws
    return workspaces


def _protect(ws: Path, protected: list[str]) -> None:
    """Give the copy its own hive profile with the same protected paths, so the usual hook guards it."""
    pdir = memory.ensure_project(ws)
    (pdir / "profile.md").write_text("# Project profile\n\n## Protected paths\n" + "".join(f"- {p}\n" for p in protected))


async def solo(key: str, goal: str, ws: Path, done: list[str], protected: list[str], budget: float | None,
               run_dir: Path) -> dict:
    model = models.get(key)
    extra = SOLO_PROMPT
    extra += "\n\nAcceptance: " + ("; ".join(f"`{c}`" for c in done) if done else "use the project's own tests.")
    extra += "\n\nProtected paths: " + (", ".join(protected) or "none")

    _protect(ws, protected)
    args = ["--model", model.id, "--effort", model.queen_effort or "high", "--append-system-prompt", extra,
            "--permission-mode", "acceptEdits", "--allowedTools", *SOLO_TOOLS, "--disallowedTools", "Agent", "Task",
            "--settings", json.dumps(PROTECT_HOOK), "--setting-sources", "project,local",
            *(["--max-budget-usd", f"{budget:g}"] if budget else [])]
    env = {**os.environ, "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "40"}
    entry = {"model": key, "name": model.name, "workspace": str(ws)}
    started = time.time()
    result = await asyncio.to_thread(claude.print_mode, args, goal, ws, env)
    if result.get("is_error"):   # a failed baseline is still a data point
        entry["error"] = str(result.get("result") or result.get("subtype"))[:200]
    total = Tokens()
    for usage in (result.get("modelUsage") or {}).values():
        total.add(Tokens.from_usage(usage))
    checks = verify.run_checks(done, ws) if done else []
    entry.update({
        "cost_usd": result.get("total_cost_usd"),
        "duration_ms": result.get("duration_ms") or int((time.time() - started) * 1000),
        "turns": result.get("num_turns"),
        "subtype": result.get("subtype", "no_result"),
        "tokens": total.to_dict(),
        "checks": checks,
        "passed": verify.passed(checks),
    })
    _git(ws, "add", "-A")
    diff = _git(ws, "diff", "--cached", "HEAD").stdout
    diff_path = run_dir / f"compare-{key}.diff"
    diff_path.write_text(diff)
    entry["diff"] = str(diff_path)
    return entry


async def run_all(goal: str, workspaces: dict[str, Path], done: list[str], protected: list[str],
                  budget: float | None, run_dir: Path) -> list[dict]:
    async def one(key: str, ws: Path) -> dict:
        print(f"⚖️  {models.get(key).name} alone: working…", flush=True)
        entry = await solo(key, goal, ws, done, protected, budget, run_dir)
        state = "error: " + entry["error"] if entry.get("error") else ("passed" if entry["passed"] else
                                                                       "failed" if entry["passed"] is False else "done")
        print(f"⚖️  {entry['name']} alone: {state} · ${entry['cost_usd'] or 0:.3f}", flush=True)
        return entry

    try:
        return list(await asyncio.gather(*(one(k, ws) for k, ws in workspaces.items())))
    finally:
        cleanup(workspaces)


def cleanup(workspaces: dict[str, Path]) -> None:
    for ws in workspaces.values():
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(memory.project_dir(ws), ignore_errors=True)
    parents = {ws.parent for ws in workspaces.values()}
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass
