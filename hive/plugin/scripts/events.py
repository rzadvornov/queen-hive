"""Hook: append the hive's live events (bees, checks, the Queen's messages) to the run's event log.

Only active in a session started by `hive`, which sets HIVE_RUN_DIR; the dashboard reads the log.
Stdlib only, and never blocks anything: every path ends with exit code 0.

Claude Code and Codex send the same hook payloads; Gemini CLI events are translated first.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from hivecore import label_of, stage_of


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


def failed(report: str) -> bool:
    """A builder's report ends with "Result: passed" or "Result: failed"."""
    return bool(re.search(r"^\W*result\W+failed\b", report, re.I | re.M))


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


DISPATCH_TOOLS = {"Agent", "Task", "spawn_agent", "invoke_agent", "scout", "builder", "reviewer"}
GEMINI_EVENTS = {"BeforeTool": "PreToolUse", "AfterTool": "PostToolUse", "AfterAgent": "Stop"}


def first_line(text: str) -> str:
    return next((line.strip() for line in str(text).splitlines() if line.strip()), "")


def _text(content) -> str:
    """Tool output as text: a string, or a list of parts like [{"text": …}]."""
    if isinstance(content, list):
        return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def _last_reply(transcript: Path) -> str:
    """The model's last reply in a Gemini chat log; the hook's own prompt_response can repeat streamed text."""
    replies = {}
    try:
        for line in transcript.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("type") == "gemini" and record.get("id"):
                replies[record["id"]] = _text(record.get("content") or "")
    except OSError:
        return ""
    return next((text for text in reversed(list(replies.values())) if text.strip()), "")


def from_gemini(data: dict) -> dict | None:
    """A Gemini CLI hook payload in Claude Code's terms; None for a sub-agent's own tool calls."""
    transcript = Path(data.get("transcript_path") or "")
    if transcript.name and transcript.parent.name != "chats":   # sub-agent logs sit in chats/<session id>/
        return None
    event = GEMINI_EVENTS[data["hook_event_name"]]
    tool, response = data.get("tool_name"), data.get("tool_response") or {}
    text = _text(response.get("llmContent") or response.get("returnDisplay") or "") if isinstance(response, dict) else str(response)
    if event == "PostToolUse" and tool in DISPATCH_TOOLS:   # the bee's report is the tool's result
        tool_input = data.get("tool_input") or {}
        brief = tool_input.get("prompt") or tool_input.get("query") or ""
        return {"hook_event_name": "SubagentStop", "description": first_line(brief),
                "agent_type": tool_input.get("agent_name") or tool, "last_assistant_message": text}
    if event == "PostToolUse" and tool == "run_shell_command":
        code = re.search(r"Exit Code: (-?\d+)", text)
        failed = bool(response.get("error")) if isinstance(response, dict) else False
        if failed or (code and code.group(1) != "0"):
            event = "PostToolUseFailure"
        return {**data, "hook_event_name": event, "tool_name": "Bash", "tool_response": text}
    if event == "Stop":
        return {"hook_event_name": "Stop", "last_assistant_message": _last_reply(transcript) or data.get("prompt_response") or ""}
    return {**data, "hook_event_name": event}


def handle(run_dir: Path, data: dict) -> None:
    if data.get("hook_event_name") in GEMINI_EVENTS:
        data = from_gemini(data)
        if data is None:
            return
    event = data.get("hook_event_name")
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    by_bee = bool(data.get("agent_id")) and event != "SubagentStop"
    if by_bee:
        return
    if event == "PreToolUse" and tool in DISPATCH_TOOLS:
        brief = tool_input.get("prompt") or tool_input.get("message") or tool_input.get("query") or ""
        description = tool_input.get("description") or first_line(brief)
        label = label_of(description)
        agent = tool_input.get("subagent_type") or tool_input.get("agent_type") or tool_input.get("agent_name") or tool
        emit(run_dir, "dispatch", id=data.get("tool_use_id"), label=label, agent=agent, stage=stage_of(agent, label),
             description=description, prompt=brief)
    elif event in ("PostToolUse", "PostToolUseFailure") and tool == "Bash":
        command = tool_input.get("command", "")
        command = " ".join(command) if isinstance(command, list) else command
        if "/.hive/" in command:   # the Queen updating hive memory, not checking work
            return
        response = data.get("tool_response")
        output = (f"{response.get('stdout', '')}\n{response.get('stderr', '')}" if isinstance(response, dict)
                  else str(response or data.get("error") or ""))
        emit(run_dir, "check", command=command, ok=event == "PostToolUse", output=output.strip()[-2000:])
    elif event == "SubagentStop":
        meta, path = bee_meta(data)
        description = meta.get("description") or data.get("description", "")
        label = label_of(description)
        text = data.get("last_assistant_message") or (last_text(path) if path else "")
        emit(run_dir, "report", id=meta.get("toolUseId"), label=label,
             stage=stage_of(meta.get("agentType") or data.get("agent_type") or "?", label), ok=not failed(text),
             text=text[-4000:])
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
