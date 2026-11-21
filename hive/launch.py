"""Run a hive session in Claude Code: its own interface in a terminal, `claude -p` when headless.

Claude Code runs as a child process. While it runs, the plugin's hooks write the live event log
for the dashboard (and for the progress lines of a headless run). When it exits, the session's
transcript gives the run records and reports.
"""

import asyncio
import contextlib
import dataclasses
import json
import os
import shutil
import signal
import subprocess
import threading
import uuid
from pathlib import Path

from hive import PLUGIN_DIR, claude, compare, memory, stats, transcript, verify
from hive.folders import start_point
from hive.modes import Policy
from hive.render import EventLog, format_event
from hive.router import Router
from hive.session import SUBAGENT_ENV, Job, build_record, new_run_dir, plugin_for, queen_prompt

SESSION_NOTE = """
# Session
This is Claude Code's own interface. The user may send several goals and follow-ups in this session.
Run the full workflow (briefs, verification, review, memory, hive-summary block) for each goal that changes
something. For plain questions, just answer without a hive-summary block.
The hive's own rules and bees, which a retro may edit, are in {plugin} (rules/queen.md, agents/<name>.md):
edit them there, not in a copy."""

WAGGLE_NOTE = """
After each finished job, right after its hive-summary block, run the `haiku-hive:waggle` skill for that job,
unless the user asked to skip the retro."""


def system_prompt(job: Job, pdir: Path, start) -> str:
    text = queen_prompt(job, pdir, start) + SESSION_NOTE.format(plugin=PLUGIN_DIR)
    return text + WAGGLE_NOTE if job.waggle else text


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
        settings["sandbox"] = {"enabled": True, "autoAllowBashIfSandboxed": True}
    if settings:
        argv += ["--settings", json.dumps(settings)]
    if job.goal:
        argv += ["--", job.goal]
    return argv


def run(job: Job, headless: bool = False) -> list[dict]:
    """Run Claude Code with the hive loaded until the user exits (or, headless, until the goal is done),
    then record and report each job."""
    target = job.folders[0]
    pdir = memory.ensure_project(target)
    run_dir = new_run_dir(pdir)
    session_id = str(uuid.uuid4())
    start = start_point(target, run_dir)
    workspaces = compare.prepare(target, run_dir, job.compare) if job.compare else {}
    EventLog(run_dir / "events.jsonl").emit(
        "run_start", goal=job.goal, queen=job.queen.key, workers=job.workers.key, mode=job.mode,
        folders=[str(f) for f in job.folders], project_dir=str(pdir), review=job.review, compare=job.compare,
        session_id=session_id)

    argv = command(job, pdir, system_prompt(job, pdir, start), plugin_for(job.bee_models()), session_id,
                   claude.installed_plugins("haiku-hive"))
    env = {**os.environ, **SUBAGENT_ENV, "HIVE_RUN_DIR": str(run_dir)}
    roles = "".join(f" ({bee}: {model.name})" for bee, model in job.roles.items())
    print(f"👑 Queen: {job.queen.name} · 🐝 bees: {job.workers.name}{roles} · mode: {job.mode} · review: {job.review}"
          + (f" · budget ${job.budget:g}" if headless and job.budget else ""))
    with contextlib.ExitStack() as stack:
        if job.local_models():   # some bees run locally: Claude Code talks to the router, which splits the traffic
            env["ANTHROPIC_BASE_URL"] = stack.enter_context(Router(job.local_models())).url
        _run(argv, target, env, run_dir, headless, job.budget)
    return finish(job, pdir, run_dir, start, session_id, workspaces)


def _run(argv: list[str], target: Path, env: dict, run_dir: Path, headless: bool, budget: float | None) -> None:
    if headless:
        argv[1:1] = ["-p", "--output-format", "json", "--permission-prompts", "none",
                     *(["--max-budget-usd", f"{budget:g}"] if budget else [])]
        _headless(argv, target, env, run_dir / "events.jsonl")
    else:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl-C belongs to Claude Code
        try:
            subprocess.run(argv, cwd=target, env=env)
        finally:
            signal.signal(signal.SIGINT, previous)


def _headless(argv: list[str], cwd: Path, env: dict, events: Path) -> dict:
    """Run `claude -p`, printing the event log as the hooks write it; returns Claude Code's JSON result."""
    stop = threading.Event()
    printer = threading.Thread(target=follow, args=(events, stop), daemon=True)
    printer.start()
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        stop.set()
        printer.join()
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        result = {"is_error": True, "subtype": "no_result", "result": (done.stderr or done.stdout).strip()[-500:]}
    if result.get("is_error"):
        print(f"💥 the hive stopped: {result.get('subtype')}: {str(result.get('result') or '').strip()[:300]}")
    return result


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


def finish(job: Job, pdir: Path, run_dir: Path, start, session_id: str, workspaces: dict[str, Path]) -> list[dict]:
    path = transcript.locate(session_id)
    if not path:
        print("🐝 no transcript for this session, so there is nothing to report.")
        shutil.rmtree(run_dir, ignore_errors=True)
        return []
    traces, exact = transcript.jobs(path)
    if not traces:
        shutil.rmtree(run_dir, ignore_errors=True)
        if exact:
            print(f"🐝 session cost ${exact:.2f} · no hive job in it, so no run was recorded.")
        return []

    records = []
    for index, (trace, job_dir) in enumerate(zip(traces, split_events(run_dir, pdir, traces))):
        last = index == len(traces) - 1
        goal = trace.prompt or job.goal
        cmds = verify.acceptance_commands(job.done, trace.summary, memory.commands(pdir))
        results = verify.run_checks(cmds, job.folders[0]) if cmds and last else []   # the files are as the last job left them
        log = EventLog(job_dir / "events.jsonl")
        for res in results:
            log.emit("acceptance", **res)
        compared = []
        if workspaces and last:
            compared = asyncio.run(compare.run_all(goal, workspaces, cmds, memory.protected_paths(pdir), job.budget, job_dir))
        record = build_record(dataclasses.replace(job, goal=goal), pdir, job_dir, trace.tracker.started, start,
                              trace.tracker, cmds, results, compared, trace.summary)
        stats.save(record, job_dir)
        log.emit("run_end", status=record["status"], cost_usd=record["hive"]["cost_usd"],
                 passed=record["acceptance"]["passed"], record=record["path"])
        stats.print_report(record)
        records.append(record)
    if exact and len(traces) > 1:
        print(f"🐝 session cost ${exact:.2f} for {len(traces)} jobs")
    return records


def split_events(run_dir: Path, pdir: Path, traces: list) -> list[Path]:
    """One run folder per job: the session's event log is cut at each job's start."""
    path = run_dir / "events.jsonl"
    events = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    start = next((e for e in events if e.get("kind") == "run_start"), {"kind": "run_start"})
    rest = [e for e in events if e.get("kind") != "run_start"]
    dirs = [run_dir] + [new_run_dir(pdir) for _ in traces[1:]]
    bounds = [t.tracker.started for t in traces[1:]] + [float("inf")]
    begin = float("-inf")
    for trace, job_dir, end in zip(traces, dirs, bounds):
        lines = [{**start, "goal": trace.prompt or start.get("goal", ""), "ts": trace.tracker.started}]
        lines += [e for e in rest if begin <= e.get("ts", 0) < end]
        (job_dir / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in lines))
        begin = end
    return dirs
