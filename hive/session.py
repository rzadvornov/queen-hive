"""Run one job through the hive: Queen session, acceptance check, comparison, statistics."""

import asyncio
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from hive import PLUGIN_DIR, compare, memory, models, stats, verify
from hive.folders import StartPoint, start_point
from hive.modes import Policy
from hive.render import EventLog, Tracker

REVIEW_LEVELS = {
    "full": "Run the full independent review with the default lenses for this task type.",
    "light": "Run a light independent review: only the `goal` and `tests` lenses (for non-coding tasks: `goal` only).",
    "off": "Skip the independent review this time. Still verify every brief yourself.",
}

SUBAGENT_ENV = {
    "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",   # only the hive's own bees exist
    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",      # bees can't spawn bees
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "5",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "40",
}


@dataclass
class Job:
    goal: str
    folders: list[Path]
    queen: models.Model
    workers: models.Model
    mode: str
    review: str = "full"
    lenses: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    budget: float | None = 5.0
    compare: list[str] = field(default_factory=list)
    verbose: bool = False
    waggle: bool = True   # run a retro after each finished job


WAGGLE_PROMPT = "/haiku-hive:waggle"


def plugin_for(workers: models.Model) -> Path:
    """The plugin to load. For non-default workers, a copy with the bees' model swapped."""
    default = models.get(models.DEFAULT_WORKERS)
    if workers.key == default.key:
        return PLUGIN_DIR
    target = memory.hive_home() / "plugins" / workers.key
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(PLUGIN_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    for agent in (target / "agents").glob("*.md"):
        agent.write_text(re.sub(r"^model: .*$", f"model: {workers.id}", agent.read_text(), count=1, flags=re.M))
    return target


def queen_prompt(job: Job, pdir: Path, start: StartPoint | None) -> str:
    rules = (PLUGIN_DIR / "rules" / "queen.md").read_text()
    target, others = job.folders[0], job.folders[1:]
    protected = memory.protected_paths(pdir)
    parts = [
        rules,
        "\n# This run",
        f"- Project folder (working directory): {target}",
        f"- Other granted folders: {', '.join(map(str, others))}" if others else "",
        f"- Hive memory folder for this project: {pdir} (profile.md, progress.md, decisions.md, known-issues.md). "
        "Write memory only there.",
        f"- Protected paths: {', '.join(protected)}" if protected else "- Protected paths: none listed",
        f"- Worker bees run on {job.workers.name}.",
        f"- {start.instructions()}" if start else "",
        f"- Review: {REVIEW_LEVELS[job.review]}",
        f"- Use exactly these review lenses: {', '.join(job.lenses)}." if job.lenses and job.review != "off" else "",
        "- The user's acceptance command(s), which must pass at the end: " + "; ".join(f"`{c}`" for c in job.done)
        if job.done else "",
    ]
    if job.mode == "plan":
        parts.append("- Plan mode: first explore read-only (you may send scouts), then present your plan with "
                     "ExitPlanMode as the list of briefs, each with its Done when, plus the review lenses you will use. "
                     "Only after the user approves do you start building.")
    parts += [
        "\n# Project profile\n" + memory.read(pdir, "profile.md"),
        "\n# Known issues\n" + memory.read(pdir, "known-issues.md"),
        "\n# Recent progress\n" + memory.tail(pdir, "progress.md", 10),
    ]
    return "\n".join(p for p in parts if p)


def build_options(job: Job, policy: Policy, pdir: Path, system: str, plugin: Path) -> ClaudeAgentOptions:
    for leftover in ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_SUBAGENT_MODEL"):
        if os.environ.get(leftover):
            print(f"⚠️  {leftover} is set in your environment and overrides the bees' model.")
    return ClaudeAgentOptions(
        model=job.queen.id,
        effort=job.queen.queen_effort,
        system_prompt={"type": "preset", "preset": "claude_code", "append": system},
        plugins=[{"type": "local", "path": str(plugin)}],
        cwd=str(job.folders[0]),
        add_dirs=[*job.folders[1:], pdir],
        permission_mode=policy.permission_mode,
        allowed_tools=policy.allowed_tools,
        disallowed_tools=["Agent(fork)"],
        can_use_tool=policy.can_use_tool,
        max_budget_usd=job.budget,
        setting_sources=["project", "local"],
        env=SUBAGENT_ENV,
    )


async def converse(client: ClaudeSDKClient, prompt: str, tracker: Tracker, wait_minutes: int = 30) -> None:
    """Send one prompt and follow the reply until no bee is still out.

    If the Queen ends a turn while background bees are running, their reports
    start a new turn, so keep listening. Ctrl-C interrupts the hive instead of killing it.
    """
    async def follow() -> None:
        async for message in client.receive_response():
            tracker.handle(message)

    await client.query(prompt)
    try:
        await follow()
        deadline = time.time() + wait_minutes * 60
        while tracker.outstanding and time.time() < deadline:
            tracker.say(f"⏳ waiting for {', '.join(d.label for d in tracker.outstanding)}…")
            try:
                await asyncio.wait_for(follow(), timeout=deadline - time.time())
            except asyncio.TimeoutError:
                tracker.say("⏳ gave up waiting for the remaining bees.")
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n⏹  interrupting the hive…")
        await client.interrupt()
        async for message in client.receive_response():
            tracker.handle(message)


def new_run_dir(pdir: Path) -> Path:
    run_dir = pdir / "runs" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2))
    run_dir.mkdir(parents=True)
    return run_dir


def build_record(job: Job, pdir: Path, run_dir: Path, started: float, start: StartPoint | None, tracker: Tracker,
                 acceptance_cmds: list[str], results: list[dict], compared: list[dict], summary: dict | None) -> dict:
    hive_data = stats.hive_section(tracker)
    estimate_keys = list(dict.fromkeys([*models.DEFAULT_COMPARE, job.queen.key]))
    return {
        "id": run_dir.name,
        "started_at": started,
        "ended_at": time.time(),
        "goal": job.goal,
        "folders": [str(f) for f in job.folders],
        "project_dir": str(pdir),
        "mode": job.mode,
        "review_level": job.review,
        "lenses": job.lenses,
        "queen": {"key": job.queen.key, "id": job.queen.id, "name": job.queen.name},
        "workers": {"key": job.workers.key, "id": job.workers.id, "name": job.workers.name},
        "start_point": start.to_dict() if start else None,
        "summary": summary,
        "session_id": tracker.result.session_id if tracker.result else None,
        "status": (summary or {}).get("status") or ("failed" if hive_data["is_error"] else "done"),
        "answer": verify.strip_summary(tracker.last_queen_text),
        "hive": hive_data,
        "acceptance": {"commands": acceptance_cmds, "results": results, "passed": verify.passed(results)},
        "rate_limits": tracker.rate_limits,
        "estimates": stats.estimates(hive_data["tokens"], estimate_keys),
        "compare": compared,
        "prices_as_of": models.PRICES_AS_OF,
    }


async def run_job(job: Job) -> dict:
    target = job.folders[0]
    pdir = memory.ensure_project(target)
    run_dir = new_run_dir(pdir)
    log = EventLog(run_dir / "events.jsonl")
    started = time.time()
    log.emit("run_start", goal=job.goal, queen=job.queen.key, workers=job.workers.key, mode=job.mode,
             folders=[str(f) for f in job.folders], project_dir=str(pdir), review=job.review, compare=job.compare)

    for folder in job.folders:
        print(f"📂 access granted: {folder}")
    print(f"👑 Queen: {job.queen.name} · 🐝 bees: {job.workers.name} · mode: {job.mode} · review: {job.review}"
          + (f" · budget ${job.budget:g}" if job.budget else ""))

    start = start_point(target, run_dir)
    workspaces = compare.prepare(target, run_dir, job.compare) if job.compare else {}

    policy = Policy(job.mode, [*job.folders, pdir], memory.commands(pdir))
    options = build_options(job, policy, pdir, queen_prompt(job, pdir, start), plugin_for(job.workers))
    tracker = Tracker(log=log, verbose=job.verbose)
    try:
        async with ClaudeSDKClient(options=options) as client:
            await converse(client, job.goal, tracker)
    except Exception as error:  # noqa: BLE001 - still record what happened
        print(f"💥 the hive stopped: {str(error).splitlines()[0] if str(error) else type(error).__name__}")
        log.emit("error", error=str(error)[:2000])
        _maybe_mark_unavailable(job.queen, tracker, str(error))

    if tracker.agents_loaded and not any(a.startswith("haiku-hive:") for a in tracker.agents_loaded):
        print("⚠️  the hive's bees were not loaded; the Queen had no workers. Check `hive doctor`.")

    summary = verify.parse_summary(tracker.last_queen_text)
    acceptance_cmds = verify.acceptance_commands(job.done, summary, memory.commands(pdir))
    results = verify.run_checks(acceptance_cmds, target) if acceptance_cmds and tracker.result else []
    for res in results:
        log.emit("acceptance", **res)

    compared: list[dict] = []
    if workspaces:
        compared = await compare.run_all(job.goal, workspaces, acceptance_cmds, memory.protected_paths(pdir),
                                         job.budget, run_dir)

    record = build_record(job, pdir, run_dir, started, start, tracker, acceptance_cmds, results, compared, summary)
    stats.save(record, run_dir)
    log.emit("run_end", status=record["status"], cost_usd=record["hive"]["cost_usd"],
             passed=record["acceptance"]["passed"], record=record["path"])
    stats.print_report(record)
    return record


def _maybe_mark_unavailable(queen: models.Model, tracker: Tracker, error: str) -> None:
    text = (error + " " + (tracker.result.result or "" if tracker.result else "")).lower()
    if not tracker.dispatches and ("model" in text and any(k in text for k in ("not found", "access", "permission", "404", "403"))):
        models.mark_unavailable(queen, error)
        print(f"   {queen.name} looks unavailable for your login; it is now marked ✗. Run `hive models` to re-check.")
