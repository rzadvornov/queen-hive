"""Run a hive session in the provider's CLI: its own interface in a terminal, its print mode when headless.

Claude Code (or Codex, or the Gemini CLI) runs as a child process. While it runs, the hive's hooks
write the live event log for the dashboard (and for the progress lines of a headless run). When it
exits, the session's transcript gives the run records and reports.
"""

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from hive import CORE_DIR, claude, compare, memory, providers
from hive.folders import start_point
from hive.modes import Policy
from hive.render import EventLog, format_event
from hive.records import finish, memory_snapshot
from hive.router import Router
from hive.job import SUBAGENT_ENV, Job, new_run_dir, plugin_for, queen_prompt

SESSION_NOTE = """
# Session
This is {product}'s own interface. The user may send several goals and follow-ups in this session.
Run the full workflow (briefs, verification, review, memory, hive-summary block) for each goal that changes
something. For plain questions, just answer without a hive-summary block.
The hive's own rules and bees, which a retro may edit, are in {plugin} (rules/queen.md, agents/<name>.md):
edit them there, not in a copy."""

WAGGLE_NOTE = """
After each finished job, right after its hive-summary block, run the `{skill}` skill for that job,
unless the user asked to skip the retro."""


def system_prompt(job: Job, pdir: Path, start) -> str:
    text = queen_prompt(job, pdir, start) + SESSION_NOTE.format(product=providers.PROVIDERS[job.provider].product,
                                                                 plugin=CORE_DIR)
    skill = "haiku-hive:waggle" if job.provider == "claude" else "waggle"
    return text + WAGGLE_NOTE.format(skill=skill) if job.waggle else text


def command(job: Job, pdir: Path, system: str, plugin: Path, session_id: str, installed: list[str] = ()) -> list[str]:
    """The `claude` command line. `installed` copies of the hive's plugin are switched off for this session,
    so the bees and hooks don't load twice."""
    policy = Policy(job.mode, [*job.folders, pdir], memory.commands(pdir))
    argv = [
        claude.binary(),
        "--plugin-dir", str(plugin),
        "--append-system-prompt", system,
        "--model", job.queen.id,
        "--session-id", session_id,
        "--name", f"🐝 hive · {job.folders[0].name}",
        "--permission-mode", policy.permission_mode,
        "--allowedTools", *policy.allowed_tools,
        "--disallowedTools", "Agent(fork)",
        "--add-dir", *map(str, job.folders[1:]), str(pdir),
    ]
    if job.queen.queen_effort:
        argv += ["--effort", job.queen.queen_effort]
    settings = {}
    if installed:
        settings["enabledPlugins"] = {plugin_id: False for plugin_id in installed}
    if job.sandbox:
        settings["sandbox"] = compare.SANDBOX
    if settings:
        argv += ["--settings", json.dumps(settings)]
    if job.goal:
        argv += ["--", job.goal]
    return argv


def run(job: Job, headless: bool = False) -> list[dict]:
    """Run the provider's CLI with the hive loaded until the user exits (or, headless, until the goal is done),
    then record and report each job."""
    target = job.folders[0]
    pdir = memory.ensure_project(target)
    run_dir = new_run_dir(pdir)
    session_id = str(uuid.uuid4())
    start = start_point(target, run_dir)
    memory_before = memory_snapshot(pdir)
    workspaces = compare.prepare(target, run_dir, job.compare) if job.compare else {}
    EventLog(run_dir / "events.jsonl").emit(
        "run_start", goal=job.goal, queen=job.queen.key, workers=job.workers.key, mode=job.mode,
        folders=[str(f) for f in job.folders], project_dir=str(pdir), review=job.review, compare=job.compare,
        session_id=session_id, provider=job.provider)

    system = system_prompt(job, pdir, start)
    env = {**os.environ, "HIVE_RUN_DIR": str(run_dir), "HIVE_CORE_DIR": str(CORE_DIR)}
    if job.provider == "claude":
        argv = command(job, pdir, system, plugin_for(job.bee_models()), session_id, claude.installed_plugins("haiku-hive"))
        env.update(SUBAGENT_ENV)
        if headless:
            argv[1:1] = ["-p", "--output-format", "json", "--permission-prompts", "none",
                         *(["--max-budget-usd", f"{job.budget:g}"] if job.budget else [])]
    else:
        argv, extra = providers.runtime(job.provider).command(job, pdir, system, session_id, headless)
        env.update(extra)
    roles = "".join(f" ({bee}: {model.name})" for bee, model in job.roles.items())
    print(f"👑 Queen: {job.queen.name} · 🐝 bees: {job.workers.name}{roles} · mode: {job.mode} · review: {job.review}"
          + (f" · budget ${job.budget:g}" if headless and job.budget and job.provider == "claude" else ""))
    if job.provider == "gpt":
        from hive import codex

        if not codex.hooks_trusted():
            print("⚠️  Codex doesn't run the hive's hooks yet, so protected paths aren't guarded and there's no live log: "
                  + codex.TRUST_HINT.format(home=codex.home()))
    started = time.time()
    with contextlib.ExitStack() as stack:
        if job.local_models():   # some bees run locally: Claude Code talks to the router, which splits the traffic
            env["ANTHROPIC_BASE_URL"] = stack.enter_context(Router(job.local_models())).url
        _run(argv, target, env, run_dir, headless, job.provider)
    return finish(job, pdir, run_dir, start, session_id, workspaces, headless, memory_before, started)


def _run(argv: list[str], target: Path, env: dict, run_dir: Path, headless: bool, provider: str = "claude") -> None:
    if headless:
        _headless(argv, target, env, run_dir / "events.jsonl", provider)
    else:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl-C belongs to the CLI
        try:
            subprocess.run(argv, cwd=target, env=env)
        finally:
            signal.signal(signal.SIGINT, previous)


def _headless(argv: list[str], cwd: Path, env: dict, events: Path, provider: str = "claude") -> str | None:
    """Run the CLI's print mode, printing the event log as the hooks write it; returns why it failed, or None."""
    stop = threading.Event()
    printer = threading.Thread(target=follow, args=(events, stop), daemon=True)
    printer.start()
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        stop.set()
        printer.join()
    check = failure if provider == "claude" else providers.runtime(provider).failure
    error = check(done.stdout, done.stderr, done.returncode)
    if error:
        print(f"💥 the hive stopped: {error.strip()[:300]}")
    return error


def failure(stdout: str, stderr: str, code: int) -> str | None:
    """Why a `claude -p --output-format json` run failed, or None."""
    try:
        result = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return "no_result: " + (stderr or stdout).strip()[-500:]
    if result.get("is_error"):
        return f"{result.get('subtype')}: {str(result.get('result') or '').strip()}"
    return None


def follow(path: Path, stop: threading.Event, interval: float = 0.3) -> None:
    """Print each complete line of an event log as it is appended, until stop is set and the log is drained."""
    position = 0
    while True:
        stopping = stop.is_set()
        if path.exists():
            with path.open("rb") as handle:
                handle.seek(position)
                chunk = handle.read()
            complete = chunk[: chunk.rfind(b"\n") + 1]
            position += len(complete)
            for line in complete.decode(errors="replace").splitlines():
                try:
                    text = format_event(json.loads(line))
                except ValueError:
                    continue
                if text:
                    print(text, flush=True)
        if stopping:
            return
        stop.wait(interval)
