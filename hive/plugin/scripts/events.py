"""Hook: append the hive's live events (bees, checks, the Queen's messages) to the run's event log.

Only active in a session started by `hive`, which sets HIVE_RUN_DIR; the dashboard reads the log.
Stdlib only, and never blocks anything: every path ends with exit code 0.
"""

import json
import os
import sys
import time
from pathlib import Path

from hivecore import stage_of


def emit(run_dir: Path, kind: str, **data) -> None:
    with (run_dir / "events.jsonl").open("a") as handle:
        handle.write(json.dumps({"ts": time.time(), "kind": kind, **data}, ensure_ascii=False, default=str) + "\n")


def last_text(path: Path) -> str:
    """The last assistant text in a transcript."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        texts = [b.get("text", "") for b in (entry.get("message") or {}).get("content") or []
                 if isinstance(b, dict) and b.get("type") == "text"]
        if any(t.strip() for t in texts):
            return "\n".join(texts)
    return ""


def bee_meta(data: dict) -> tuple[dict, Path | None]:
    """The finished bee's metadata (toolUseId, description) and transcript."""
    raw = data.get("agent_transcript_path")
    if raw:
        path = Path(raw)
    elif data.get("transcript_path") and data.get("agent_id"):
        path = Path(data["transcript_path"]).with_suffix("") / "subagents" / f"agent-{data['agent_id']}.jsonl"
    else:
        return {}, None
    try:
        return json.loads(path.with_name(path.name.replace(".jsonl", ".meta.json")).read_text()), path
    except (OSError, ValueError):
        return {}, path


def handle(run_dir: Path, data: dict) -> None:
    event = data.get("hook_event_name")
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    by_bee = bool(data.get("agent_id")) and event != "SubagentStop"
    if by_bee:
        return
    if event == "PreToolUse" and tool in ("Agent", "Task"):
        description = tool_input.get("description", "")
        label = description.split()[0] if description else "#"
        agent = tool_input.get("subagent_type", "?")
        emit(run_dir, "dispatch", id=data.get("tool_use_id"), label=label, agent=agent, stage=stage_of(agent, label),
             description=description, prompt=tool_input.get("prompt", ""))
    elif event in ("PostToolUse", "PostToolUseFailure") and tool == "Bash":
        command = tool_input.get("command", "")
        if "/.hive/" in command:   # the Queen updating hive memory, not checking work
            return
        response = data.get("tool_response")
        output = (f"{response.get('stdout', '')}\n{response.get('stderr', '')}" if isinstance(response, dict)
                  else str(response or data.get("error") or ""))
        emit(run_dir, "check", command=command, ok=event == "PostToolUse", output=output.strip()[-2000:])
    elif event == "SubagentStop":
        meta, path = bee_meta(data)
        description = meta.get("description", "")
        label = description.split()[0] if description else "#"
        text = data.get("last_assistant_message") or (last_text(path) if path else "")
        emit(run_dir, "report", id=meta.get("toolUseId"), label=label,
             stage=stage_of(meta.get("agentType") or data.get("agent_type") or "?", label), ok=True, text=text[-4000:])
    elif event == "Stop":
        text = data.get("last_assistant_message") or last_text(Path(data.get("transcript_path") or ""))
        if text:
            emit(run_dir, "queen_text", text=text)


def main() -> None:
    run_dir = os.environ.get("HIVE_RUN_DIR")
    if not run_dir or not Path(run_dir).is_dir():
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    try:
        handle(Path(run_dir), data)
    except OSError:
        pass


if __name__ == "__main__":
    main()
