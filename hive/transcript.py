"""Read a finished Claude Code session from its transcript: one Tracker per hive job in it.

The transcript is Claude Code's own JSONL file, not a stable API, so everything here
tolerates missing fields: a format change degrades the report instead of crashing it.
"""

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from hive import pricing, verify
from hive.pricing import Tokens
from hive.render import AGENT_TOOLS, Dispatch, Result, Tracker, result_text, stage_of

_NOT_PROMPTS = ("<task-notification>", "<system-reminder>", "<local-command", "<command-message>")


@dataclass
class JobTrace:
    """One job in a session: from the user's goal to the Queen's hive-summary block."""

    prompt: str
    tracker: Tracker
    summary: dict | None = None
    _pending_checks: dict[str, str] = field(default_factory=dict)


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def locate(session_id: str) -> Path | None:
    """The transcript of a session, whatever folder it ran in."""
    found = sorted((config_dir() / "projects").glob(f"*/{session_id}.jsonl"))
    return found[0] if found else None


def _lines(path: Path) -> list[dict]:
    entries = []
    try:
        text = path.read_text()
    except OSError:
        return entries
    for line in text.splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _ts(entry: dict) -> float | None:
    raw = entry.get("timestamp")
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _prompt(entry: dict) -> str | None:
    """The text the user typed, or None for tool results, reminders and bee notifications."""
    if entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str) or not content.strip():
        return None
    text = content.strip()
    if text.startswith("<command-name>"):   # a slash command: keep "/name args"
        name = text.split("<command-name>", 1)[1].split("</command-name>", 1)[0]
        args = text.split("<command-args>", 1)[1].split("</command-args>", 1)[0] if "<command-args>" in text else ""
        return f"{name} {args}".strip()
    return None if text.startswith(_NOT_PROMPTS) else text


def _bees(session_dir: Path) -> dict[str, tuple[str, str, list[dict]]]:
    """Agent tool_use id → (agent type, description, the bee's transcript entries)."""
    bees = {}
    for meta_path in sorted((session_dir / "subagents").glob("agent-*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        tool_use_id = meta.get("toolUseId")
        if tool_use_id:
            entries = _lines(meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl")))
            bees[tool_use_id] = (meta.get("agentType", "?"), meta.get("description", ""), entries)
    return bees


def _add_usage(tracker: Tracker, stage: str, entry: dict, seen: set[str]) -> None:
    message = entry.get("message") or {}
    key = message.get("id") or entry.get("uuid")
    if not message.get("usage") or not message.get("model") or key in seen:
        return   # Claude Code writes one entry per content block, each repeating the message's usage
    seen.add(key)
    tracker.usage.setdefault((stage, message["model"]), Tokens()).add(Tokens.from_usage(message["usage"]))


def _cost_state(entries: list[dict]) -> dict:
    return next((e for e in reversed(entries) if e.get("type") == "cost-state"), {})


def jobs(path: Path) -> tuple[list[JobTrace], float | None]:
    """The hive jobs in a session, and Claude Code's exact cost for the whole session."""
    entries = _lines(path)
    traces: list[JobTrace] = []
    current: JobTrace | None = None
    other = Tracker()   # tokens of turns outside any job (questions, the retro)
    seen: set[str] = set()

    def open_job(prompt: str, ts: float | None) -> JobTrace:
        trace = JobTrace(prompt, Tracker())
        trace.tracker.started = ts or trace.tracker.started
        return trace

    for entry in entries:
        kind = entry.get("type")
        if kind not in ("user", "assistant") or entry.get("isSidechain"):
            continue
        ts = _ts(entry)
        if kind == "user":
            prompt = _prompt(entry)
            if prompt is not None:
                current = current or open_job(prompt, ts)   # later prompts are follow-ups in the same job
                continue
            if current:
                _tool_results(current, entry)
            continue

        tracker = current.tracker if current else other
        _add_usage(tracker, "queen", entry, seen)
        if ts:
            tracker.ended = ts
        for block in (entry.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                tracker.last_queen_text = block["text"]
                summary = verify.parse_summary(block["text"])
                if summary is not None and current:
                    current.summary = summary
                    traces.append(current)
                    current = None
            elif block.get("type") == "tool_use" and current:
                _tool_use(current, block)
    if current and current.tracker.dispatches:   # unfinished, but bees worked: still a job
        traces.append(current)
    elif current:
        for key, tokens in current.tracker.usage.items():
            other.usage.setdefault(key, Tokens()).add(tokens)

    bees = _bees(path.with_suffix(""))
    for trace in traces:
        for tool_use_id, dispatch in trace.tracker.dispatches.items():
            agent, description, bee_entries = bees.get(tool_use_id, (dispatch.agent, "", []))
            for entry in bee_entries:
                if entry.get("type") == "assistant":
                    _add_usage(trace.tracker, dispatch.stage, entry, seen)
    exact = _cost_state(entries).get("totalCostUSD")
    _price(traces, other, exact, path.stem)
    return traces, exact


def _tool_use(trace: JobTrace, block: dict) -> None:
    tracker, data = trace.tracker, block.get("input") or {}
    if block.get("name") in AGENT_TOOLS:
        description = data.get("description", "")
        label = description.split()[0] if description else f"#{len(tracker.dispatches) + 1}"
        agent = data.get("subagent_type", "?")
        tracker.dispatches[block.get("id", label)] = Dispatch(label, agent, stage_of(agent, label), description)
        tracker.label_counts[label] = tracker.label_counts.get(label, 0) + 1
    elif block.get("name") == "Bash" and "/.hive/" not in data.get("command", ""):
        trace._pending_checks[block.get("id", "")] = data.get("command", "")


def _tool_results(trace: JobTrace, entry: dict) -> None:
    content = (entry.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id")
        if tool_use_id in trace._pending_checks:
            trace.tracker.checks.append({"command": trace._pending_checks.pop(tool_use_id), "ok": not block.get("is_error")})
        elif tool_use_id in trace.tracker.dispatches:
            text = result_text(block.get("content"))
            bee = trace.tracker.dispatches[tool_use_id]
            bee.status = "launched" if "async_launched" in text else "failed" if block.get("is_error") else "reported"


def _estimate(tracker: Tracker) -> float:
    return sum(pricing.cost_by_id(tokens, model, "1h" if stage == "queen" else "5m") or 0.0
               for (stage, model), tokens in tracker.usage.items())


def _price(traces: list[JobTrace], other: Tracker, exact: float | None, session_id: str) -> None:
    """Each job's cost: its share of Claude Code's exact session cost, else the token estimate."""
    estimates = [_estimate(t.tracker) for t in traces]
    total = sum(estimates) + _estimate(other)
    factor = exact / total if exact and total else 1.0
    for trace, estimate in zip(traces, estimates):
        tracker = trace.tracker
        tracker.ended = tracker.ended or tracker.started
        tracker.result = Result(session_id=session_id, total_cost_usd=estimate * factor,
                                duration_ms=int((tracker.ended - tracker.started) * 1000))
