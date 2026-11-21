"""A run's event log, the per-job data the statistics are built from, and how events print in headless runs."""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from hive.pricing import Tokens

from hivecore import stage_of  # noqa: F401 - re-exported

AGENT_TOOLS = ("Agent", "Task")
_SUMMARY_RE = re.compile(r"```hive-summary\s*\n.*?```", re.S)
_TAG_RE = re.compile(r"<([a-z-]+)>.*?</\1>", re.S)
STAGE_ICONS = {"queen": "👑", "scout": "🔎", "build": "🔨", "review": "🧐", "fix": "🩹"}


class EventLog:
    """Append-only JSONL log of a run; the plugin's hooks and the dashboard use the same file."""

    def __init__(self, path: Path | None):
        self.path = path

    def emit(self, kind: str, **data) -> None:
        if not self.path:
            return
        with self.path.open("a") as handle:
            handle.write(json.dumps({"ts": time.time(), "kind": kind, **data}, ensure_ascii=False, default=str) + "\n")


@dataclass
class Dispatch:
    label: str
    agent: str
    stage: str
    description: str
    status: str = "running"


@dataclass
class Result:
    """A job's totals, as Claude Code reports them."""

    session_id: str | None = None
    total_cost_usd: float | None = None
    duration_ms: int = 0
    duration_api_ms: int | None = None
    is_error: bool = False
    subtype: str = "success"
    model_usage: dict | None = None


@dataclass
class Tracker:
    """What one job used and did: tokens per stage and model, bees, returns and the Queen's checks."""

    usage: dict[tuple[str, str], Tokens] = field(default_factory=dict)   # (stage, model id) → tokens
    dispatches: dict[str, Dispatch] = field(default_factory=dict)       # Agent tool_use id → dispatch
    label_counts: dict[str, int] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    last_queen_text: str = ""
    result: Result | None = None
    started: float = field(default_factory=time.time)
    ended: float | None = None

    @property
    def results(self) -> list[Result]:
        return [self.result] if self.result else []

    @property
    def returns(self) -> int:
        return sum(n - 1 for label, n in self.label_counts.items() if n > 1 and label[:1] in ("B", "F"))

    def tokens_by_stage(self) -> dict[str, Tokens]:
        result: dict[str, Tokens] = {}
        for (stage, _), tokens in self.usage.items():
            result.setdefault(stage, Tokens()).add(tokens)
        return result

    def tokens_by_model(self) -> dict[str, Tokens]:
        result: dict[str, Tokens] = {}
        for (_, model), tokens in self.usage.items():
            result.setdefault(model, Tokens()).add(tokens)
        return result


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_event(event: dict) -> str | None:
    """One event of the log as a terminal line, for headless runs; None for events not worth printing."""
    kind = event.get("kind")
    if kind == "dispatch":
        stage = event.get("stage", "build")
        return f"👑 → {STAGE_ICONS.get(stage, '🐝')} {event.get('agent', '?').rsplit(':', 1)[-1]:9} {event.get('description', '')}"
    if kind == "check":
        tail = (event.get("output") or "").strip().splitlines()[-1:] or [""]
        return f"👑 🔍 $ {_short(event.get('command', ''), 160)}\n   {'✅' if event.get('ok') else '❌'} {_short(tail[0], 160)}"
    if kind == "report":
        clean = _TAG_RE.sub("", event.get("text") or "")
        first = next((line for line in clean.splitlines() if line.strip() and not line.startswith("agentId")), "")
        return f"   🐝 {event.get('label', '?')} {'📨' if event.get('ok', True) else '❌'} {_short(first, 150)}"
    if kind == "queen_text":
        visible = _SUMMARY_RE.sub("", event.get("text") or "").strip()
        return f"👑 {visible}" if visible else None
    return None
