"""Turn a finished hive session into run records: acceptance, reports, comparison, memory changes."""

import asyncio
import dataclasses
import difflib
import json
import shutil
import time
from pathlib import Path

from hive import compare, memory, providers, stats, transcript, ui, verify
from hive.render import EventLog
from hive.job import Job, build_record, new_run_dir


def approved(cmds: list[str], job: Job, pdir: Path, headless: bool) -> list[str]:
    """The acceptance commands to run here, with the user's shell and outside Claude Code's permissions.

    The user's own commands (--done, the profile's test command) always run. The Queen's run too when she
    could have run them in the session anyway (plan and auto mode, no sandbox); otherwise only if the user
    says so, because her summary could repeat a command planted in something she read.
    """
    trusted = set(job.done) | {memory.commands(pdir).get("test")}
    queen = [c for c in cmds if c not in trusted]
    if not queen or (job.mode != "ask" and not job.sandbox):
        return cmds
    listed = "\n".join(f"   $ {c}" for c in queen)
    if not headless and ui.interactive():
        print(f"🛡  The Queen's acceptance commands:\n{listed}")
        if ui.confirm("   run them here, outside Claude Code's permissions?", default=False):
            return cmds
    else:
        print(f"🛡  skipped the Queen's acceptance commands ({'ask mode' if job.mode == 'ask' else 'sandbox'}):\n{listed}")
    return [c for c in cmds if c in trusted]


def memory_snapshot(pdir: Path) -> dict[str, str]:
    return {name: memory.read(pdir, name) for name in memory.MEMORY_FILES}


def report_memory_changes(pdir: Path, before: dict[str, str]) -> dict[str, list[str]]:
    """Print the lines the session added to the hive memory: they go into every later session's instructions."""
    added = {}
    for name, old in before.items():
        new = memory.read(pdir, name)
        lines = [line[1:] for line in difflib.ndiff(old.splitlines(), new.splitlines())
                 if line.startswith("+ ") and line[2:].strip()]
        if lines:
            added[name] = [line.strip() for line in lines]
    for name, lines in added.items():
        print(f"📝 {name}: " + "; ".join(lines[:5]) + (f" (+{len(lines) - 5} more)" if len(lines) > 5 else ""))
    return added


def session_jobs(job: Job, session_id: str, started: float) -> tuple[list, float | None] | None:
    """The jobs in the session's transcript and its exact cost (Claude Code only); None without a transcript."""
    if job.provider == "claude":
        path = transcript.locate(session_id)
        return transcript.jobs(path) if path else None
    found = providers.runtime(job.provider).transcript(session_id, started, job.folders[0])
    return found[:2] if found else None


def finish(job: Job, pdir: Path, run_dir: Path, start, session_id: str, workspaces: dict[str, Path],
           headless: bool = False, memory_before: dict[str, str] | None = None, started: float | None = None) -> list[dict]:
    """Record and report each job of a finished session; returns the run records."""
    if memory_before is not None:
        report_memory_changes(pdir, memory_before)
    found = session_jobs(job, session_id, started or time.time())
    if not found:
        print("🐝 no transcript for this session, so there is nothing to report.")
        shutil.rmtree(run_dir, ignore_errors=True)
        return []
    traces, exact = found
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
        if last:   # the files are as the last job left them
            cmds = approved(cmds, job, pdir, headless)
        results = verify.run_checks(cmds, job.folders[0]) if cmds and last else []
        log = EventLog(job_dir / "events.jsonl")
        for res in results:
            log.emit("acceptance", **res)
        compared = []
        if workspaces and last:
            compared = asyncio.run(compare.run_all(goal, workspaces, cmds, memory.protected_paths(pdir), job.budget, job_dir,
                                                   job.sandbox))
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
