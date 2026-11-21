"""Read a finished Claude Code session from its transcript: one JobStats per hive job in it.

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
from hive.render import AGENT_TOOLS, Dispatch, Result, JobStats, result_text

from hivecore import label_of, stage_of

_NOT_PROMPTS = ("<task-notification>", "<system-reminder>", "<local-command", "<command-message>")


@dataclass
class JobTrace:
    """One job in a session: from the user's goal to the Queen's hive-summary block."""

    prompt: str
    tracker: JobStats
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


def _add_usage(tracker: JobStats, stage: str, entry: dict, seen: set[str]) -> None:
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
    other = JobStats()   # tokens of turns outside any job (questions, the retro)
    seen: set[str] = set()

    def open_job(prompt: str, ts: float | None) -> JobTrace:
        trace = JobTrace(prompt, JobStats())
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
        label = label_of(description, f"#{len(tracker.dispatches) + 1}")
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


def _estimate(tracker: JobStats) -> float:
    return sum(pricing.cost_by_id(tokens, model, "1h" if stage == "queen" else "5m") or 0.0
               for (stage, model), tokens in tracker.usage.items())


def _price(traces: list[JobTrace], other: JobStats, exact: float | None, session_id: str) -> None:
    """Each job's cost: its share of Claude Code's exact session cost, else the token estimate."""
    estimates = [_estimate(t.tracker) for t in traces]
    total = sum(estimates) + _estimate(other)
    factor = exact / total if exact and total else 1.0
    for trace, estimate in zip(traces, estimates):
        tracker = trace.tracker
        tracker.ended = tracker.ended or tracker.started
        tracker.result = Result(session_id=session_id, total_cost_usd=estimate * factor,
                                duration_ms=int((tracker.ended - tracker.started) * 1000))


# --- other providers' logs ----------------------------------------------------
# Codex and Gemini sessions are read into a flat list of events, then cut into jobs here like a
# Claude Code transcript: a job runs from the user's goal to the Queen's hive-summary block.
#   {"t": "prompt", "text"}                    the user typed something
#   {"t": "usage", "model", "tokens"}          one model request of the Queen
#   {"t": "text", "text"}                      the Queen wrote something
#   {"t": "dispatch", "id", "agent", "brief"}  the Queen sent a bee
#   {"t": "dispatched", "id", "ok"}            the bee's result came back
#   {"t": "check", "command", "ok"}            the Queen ran a shell command
# Every event may carry "ts". Bee usage comes separately as (brief, agent, model, tokens, ts).


def from_events(events: list[dict], bees: list[tuple[str, str, str, Tokens, float | None]],
                session_id: str) -> list[JobTrace]:
    traces: list[JobTrace] = []
    current: JobTrace | None = None
    other = JobStats()
    for event in events:
        kind, ts = event.get("t"), event.get("ts")
        if kind == "prompt":
            if current is None:
                current = JobTrace(event.get("text", ""), JobStats())
                current.tracker.started = ts or current.tracker.started
            continue
        tracker = current.tracker if current else other
        if ts:
            tracker.ended = ts
        if kind == "usage":
            tracker.usage.setdefault(("queen", event["model"]), Tokens()).add(event["tokens"])
        elif kind == "text" and event.get("text", "").strip():
            tracker.last_queen_text = event["text"]
            summary = verify.parse_summary(event["text"])
            if summary is not None and current:
                current.summary = summary
                traces.append(current)
                current = None
        elif kind == "dispatch" and current:
            brief = event.get("brief", "")
            label = label_of(brief, f"#{len(tracker.dispatches) + 1}")
            agent = event.get("agent") or "?"
            tracker.dispatches[event.get("id") or label] = Dispatch(label, agent, stage_of(agent, label), _first_line(brief))
            tracker.label_counts[label] = tracker.label_counts.get(label, 0) + 1
        elif kind == "dispatched" and current and event.get("id") in tracker.dispatches:
            tracker.dispatches[event["id"]].status = "reported" if event.get("ok", True) else "failed"
        elif kind == "check" and current and "/.hive/" not in event.get("command", ""):
            tracker.checks.append({"command": event.get("command", ""), "ok": bool(event.get("ok"))})
    if current and current.tracker.dispatches:
        traces.append(current)

    for brief, agent, model, tokens, ts in bees:   # each bee belongs to the job running when it worked
        owner = next((t for t in reversed(traces) if ts is None or t.tracker.started <= ts), traces[0] if traces else None)
        if owner:
            label = label_of(brief)
            owner.tracker.usage.setdefault((stage_of(agent or "?", label), model), Tokens()).add(tokens)
    _price(traces, other, None, session_id)
    return traces


def match_brief(prompt: str, agent: str, briefs: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """(brief, agent) a bee worked on: the Queen's brief whose first line its prompt contains, else its own prompt."""
    for brief, brief_agent in briefs.values():
        first = _first_line(brief)
        if first and first in prompt:
            return brief, agent or brief_agent
    return prompt, agent


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
