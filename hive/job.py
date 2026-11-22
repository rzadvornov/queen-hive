"""A hive job: its settings, the Queen's instructions, the bees' plugin, and its run record."""

import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from hive import PLUGIN_DIR, memory, models, portable, stats, verify
from hive.folders import StartPoint
from hive.render import JobStats

REVIEW_LEVELS = {
    "full": "Run the full independent review with the default lenses for this task type.",
    "light": "Run a light independent review: only the `goal` and `tests` lenses (for non-coding tasks: `goal` only).",
    "off": "Skip the independent review this time. Still verify every brief yourself.",
}

BEES = ("scout", "builder", "reviewer")

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
    sandbox: bool = False   # run Bash in Claude Code's sandbox: writes only inside the granted folders and temp
    roles: dict[str, models.Model] = field(default_factory=dict)   # per-bee model, e.g. {"scout": a local model}

    def bee_models(self) -> dict[str, models.Model]:
        """The model of each bee: its role's model, else the workers' model."""
        return {bee: self.roles.get(bee, self.workers) for bee in BEES}

    waggle: bool = True   # interactive: the Queen runs a retro after each finished job

    @property
    def provider(self) -> str:
        return self.queen.provider

    def local_models(self) -> dict[str, str]:
        """Local model ID → its server, for the bees that run on one."""
        return {m.id: m.base_url for m in self.bee_models().values() if m.local}


def plugin_for(bees: dict[str, models.Model]) -> Path:
    """The plugin to load. When a bee runs on another model than the default, a copy with its model swapped."""
    default = models.get(models.DEFAULT_WORKERS)
    if all(model.key == default.key for model in bees.values()):
        return PLUGIN_DIR
    target = memory.hive_home() / "plugins" / "-".join(f"{bee}={bees[bee].key}" for bee in sorted(bees)).replace(":", "_")
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(PLUGIN_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    for bee, model in bees.items():
        agent = target / "agents" / f"{bee}.md"
        agent.write_text(re.sub(r"^model: .*$", f"model: {model.id}", agent.read_text(), count=1, flags=re.M))
    return target


def queen_prompt(job: Job, pdir: Path, start: StartPoint | None) -> str:
    rules = portable.rules_for(job.provider)
    target, others = job.folders[0], job.folders[1:]
    parts = [
        rules,
        "\n# This run",
        f"- Project folder (working directory): {target}",
        f"- Other granted folders: {', '.join(map(str, others))}" if others else "",
        f"- Worker bees run on {job.workers.name}.",
        *[f"- The {bee} bee runs on {model.name}, a local model: keep its briefs short and explicit, and check its work "
          "with extra care." for bee, model in job.roles.items() if model.local],
        f"- {start.instructions()}" if start else "",
        f"- Review: {REVIEW_LEVELS[job.review]}",
        f"- Use exactly these review lenses: {', '.join(job.lenses)}." if job.lenses and job.review != "off" else "",
        "- The user's acceptance command(s), which must pass at the end: " + "; ".join(f"`{c}`" for c in job.done)
        if job.done else "",
    ]
    if job.mode == "plan":
        present = "with ExitPlanMode" if job.provider == "claude" else "in your reply"
        parts.append(f"- Plan mode: first explore read-only (you may send scouts), then present your plan {present} "
                     "as the list of briefs, each with its Done when, plus the review lenses you will use. "
                     "Only after the user approves do you start building.")
    parts.append(memory.run_context(target))
    text = "\n".join(p for p in parts if p)
    return text if job.provider == "claude" else portable.plain(text)   # `haiku-hive:init` → `init`


def new_run_dir(pdir: Path) -> Path:
    run_dir = pdir / "runs" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2))
    run_dir.mkdir(parents=True)
    return run_dir


def build_record(job: Job, pdir: Path, run_dir: Path, started: float, start: StartPoint | None, tracker: JobStats,
                 acceptance_cmds: list[str], results: list[dict], compared: list[dict], summary: dict | None) -> dict:
    hive_data = stats.hive_section(tracker)
    priced = job.queen.input > 0   # a ChatGPT-plan model has no price to compare with
    estimate_keys = list(dict.fromkeys([*models.default_compare(job.provider), *([job.queen.key] if priced else [])]))
    return {
        "id": run_dir.name,
        "started_at": started,
        "ended_at": tracker.ended or time.time(),
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
        "estimates": stats.estimates(hive_data["tokens"], estimate_keys),
        "compare": compared,
        "prices_as_of": models.prices_as_of([job.queen, *job.bee_models().values(),
                                             *(models.get(k) for k in estimate_keys)]),
        "provider": job.provider,
    }
