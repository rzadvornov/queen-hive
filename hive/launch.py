"""`hive` in a terminal: Claude Code's own interface, with the hive's plugin and Queen instructions loaded.

Claude Code runs as a child process. While it runs, the plugin's hooks write the live event log
for the dashboard. When the user exits, the session's transcript gives the run records and reports.
"""

import asyncio
import dataclasses
import json
import os
import shutil
import signal
import subprocess
import uuid
from pathlib import Path

import claude_agent_sdk

from hive import PLUGIN_DIR, compare, memory, stats, transcript, verify
from hive.folders import start_point
from hive.modes import Policy
from hive.render import EventLog
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


def claude_binary() -> str:
    """Claude Code on PATH, else the copy bundled with the SDK."""
    found = shutil.which("claude")
    if found:
        return found
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if bundled.is_file():
        return str(bundled)
    raise SystemExit("Claude Code not found: install it, or reinstall the hive so the SDK brings its own copy.")


def system_prompt(job: Job, pdir: Path, start) -> str:
    text = queen_prompt(job, pdir, start) + SESSION_NOTE.format(plugin=PLUGIN_DIR)
    return text + WAGGLE_NOTE if job.waggle else text


def command(job: Job, pdir: Path, system: str, plugin: Path, session_id: str) -> list[str]:
    policy = Policy(job.mode, [*job.folders, pdir], memory.commands(pdir))
    argv = [
        claude_binary(),
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
    if job.goal:
        argv += ["--", job.goal]
    return argv


def run(job: Job) -> list[dict]:
    """Run Claude Code with the hive loaded until the user exits, then record and report each job."""
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

    argv = command(job, pdir, system_prompt(job, pdir, start), plugin_for(job.workers), session_id)
    env = {**os.environ, **SUBAGENT_ENV, "HIVE_RUN_DIR": str(run_dir)}
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl-C belongs to Claude Code
    try:
        subprocess.run(argv, cwd=target, env=env)
    finally:
        signal.signal(signal.SIGINT, previous)
    return finish(job, pdir, run_dir, start, session_id, workspaces)


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
