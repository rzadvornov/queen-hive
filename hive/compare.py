"""Real side-by-side runs: the same goal done by one model alone, in a copy of the folder."""

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage

from hive import memory, models, verify
from hive.pricing import Tokens
from hive.render import Tracker

from hivecore import matches

SOLO_PROMPT = """You are working alone on this task: no helpers or subagents.
Do the whole job yourself, then verify it by running the acceptance command(s) below until they pass.
Never change the protected paths listed below.
Reply in the user's language."""

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


def _protect_hook(root: Path, patterns: list[str]):
    async def hook(data, tool_use_id, context):
        tool_input = data.get("tool_input") or {}
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        if raw:
            path = Path(raw)
            path = path if path.is_absolute() else root / path
            try:
                rel = str(path.resolve().relative_to(root.resolve()))
            except ValueError:
                rel = None
            if rel and any(matches(rel, p) for p in patterns):
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                               "permissionDecisionReason": f"{rel} is a protected path."}}
        return {}

    return hook


async def solo(key: str, goal: str, ws: Path, done: list[str], protected: list[str], budget: float | None,
               run_dir: Path) -> dict:
    model = models.get(key)
    extra = SOLO_PROMPT
    extra += "\n\nAcceptance: " + ("; ".join(f"`{c}`" for c in done) if done else "use the project's own tests.")
    extra += "\n\nProtected paths: " + (", ".join(protected) or "none")

    async def allow_inside(tool, data, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        raw = data.get("file_path") or data.get("notebook_path")
        if raw and not str(Path(raw).resolve()).startswith(str(ws.resolve())):
            return PermissionResultDeny(message="Stay inside the project folder.")
        return PermissionResultAllow()

    options = ClaudeAgentOptions(
        model=model.id,
        effort=model.queen_effort or "high",
        system_prompt={"type": "preset", "preset": "claude_code", "append": extra},
        cwd=str(ws),
        permission_mode="acceptEdits",
        allowed_tools=["Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "TodoWrite"],
        disallowed_tools=["Agent", "Task"],
        can_use_tool=allow_inside,
        hooks={"PreToolUse": [HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit", hooks=[_protect_hook(ws, protected)])]},
        max_budget_usd=budget,
        setting_sources=["project", "local"],
        env={"CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "40"},
    )
    tracker = Tracker(quiet=True)
    entry = {"model": key, "name": model.name, "workspace": str(ws)}
    started = time.time()
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(goal)
            async for message in client.receive_response():
                tracker.handle(message)
    except Exception as error:  # noqa: BLE001 - a failed baseline is still a data point
        entry["error"] = str(error).splitlines()[0] if str(error) else type(error).__name__

    result: ResultMessage | None = tracker.result
    total = Tokens()
    if result and result.model_usage:
        for usage in result.model_usage.values():
            total.add(Tokens.from_usage(usage))
    else:
        for tokens in tracker.usage.values():
            total.add(tokens)
    checks = verify.run_checks(done, ws) if done else []
    entry.update({
        "cost_usd": result.total_cost_usd if result else None,
        "duration_ms": result.duration_ms if result else int((time.time() - started) * 1000),
        "turns": result.num_turns if result else None,
        "subtype": result.subtype if result else "no_result",
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
    parents = {ws.parent for ws in workspaces.values()}
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass
