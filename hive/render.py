"""Follow a hive session: print 👑/🐝 progress, write the event log, count tokens per stage."""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TaskNotificationMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from hive.pricing import Tokens

from hivecore import stage_of  # noqa: F401 - re-exported

AGENT_TOOLS = ("Agent", "Task")
_SUMMARY_RE = re.compile(r"```hive-summary\s*\n.*?```", re.S)
_TAG_RE = re.compile(r"<([a-z-]+)>.*?</\1>", re.S)
STAGE_ICONS = {"queen": "👑", "scout": "🔎", "build": "🔨", "review": "🧐", "fix": "🩹"}


class EventLog:
    """Append-only JSONL log of a run; the dashboard reads the same file."""

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


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


@dataclass
class Tracker:
    log: EventLog = field(default_factory=lambda: EventLog(None))
    verbose: bool = False
    quiet: bool = False
    prefix: str = ""

    usage: dict[tuple[str, str], Tokens] = field(default_factory=dict)   # (stage, model id) → tokens
    dispatches: dict[str, Dispatch] = field(default_factory=dict)       # Agent tool_use id → dispatch
    label_counts: dict[str, int] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    rate_limits: list[dict] = field(default_factory=list)
    agents_loaded: list[str] = field(default_factory=list)
    last_queen_text: str = ""
    result: ResultMessage | None = None
    results: list[ResultMessage] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    ended: float | None = None   # set when the tracker is rebuilt from a finished transcript
    _pending_checks: dict[str, str] = field(default_factory=dict)
    _seen_messages: set[str] = field(default_factory=set)

    def say(self, text: str) -> None:
        if not self.quiet:
            print(f"{self.prefix}{text}", flush=True)

    # --- message handling -------------------------------------------------

    def handle(self, message) -> None:
        if isinstance(message, AssistantMessage):
            self._assistant(message)
        elif isinstance(message, UserMessage):
            self._user(message)
        elif isinstance(message, TaskNotificationMessage):
            self._task_done(message)
        elif isinstance(message, RateLimitEvent):
            self._rate_limit(message)
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            self.agents_loaded = [a if isinstance(a, str) else a.get("name", "") for a in message.data.get("agents", [])]
            self.log.emit("session_init", model=message.data.get("model"), agents=self.agents_loaded)
        elif isinstance(message, ResultMessage):
            self.result = message
            self.results.append(message)
            self.log.emit("turn_end", cost_usd=message.total_cost_usd, duration_ms=message.duration_ms,
                          turns=message.num_turns, model_usage=message.model_usage, subtype=message.subtype)

    def _stage(self, parent: str | None) -> str:
        return self.dispatches[parent].stage if parent in self.dispatches else "queen"

    def _assistant(self, message: AssistantMessage) -> None:
        parent = message.parent_tool_use_id
        stage = self._stage(parent)
        # The CLI may split one API message into several events that repeat its usage.
        key = message.message_id or message.uuid
        if message.usage and (key is None or key not in self._seen_messages):
            if key:
                self._seen_messages.add(key)
            self.usage.setdefault((stage, message.model), Tokens()).add(Tokens.from_usage(message.usage))
        if message.error:
            self.say(f"⚠️  {message.error}")
            self.log.emit("error", error=message.error, stage=stage)

        bee = self.dispatches.get(parent) if parent else None
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                if bee is None:
                    self.last_queen_text = block.text
                    visible = _SUMMARY_RE.sub("", block.text).strip()
                    if visible:
                        self.say(f"👑 {visible}")
                    self.log.emit("queen_text", text=block.text)
                elif self.verbose:
                    self.say(f"   🐝 {bee.label} {_short(block.text)}")
            elif isinstance(block, ToolUseBlock):
                self._tool_use(block, bee)

    def _tool_use(self, block: ToolUseBlock, bee: Dispatch | None) -> None:
        if bee is None and block.name in AGENT_TOOLS:
            description = block.input.get("description", "")
            label = description.split()[0] if description else f"#{len(self.dispatches) + 1}"
            agent = block.input.get("subagent_type", "?")
            stage = stage_of(agent, label)
            self.dispatches[block.id] = Dispatch(label, agent, stage, description)
            self.label_counts[label] = self.label_counts.get(label, 0) + 1
            again = " (again)" if self.label_counts[label] > 1 else ""
            self.say(f"👑 → {STAGE_ICONS[stage]} {agent.rsplit(':', 1)[-1]:9} {description}{again}")
            self.log.emit("dispatch", id=block.id, label=label, agent=agent, stage=stage,
                          description=description, prompt=block.input.get("prompt", ""))
        elif bee is None and block.name == "Bash":
            command = block.input.get("command", "")
            if "/.hive/" in command:   # the Queen updating hive memory, not checking work
                self.say("👑 📝 updating hive memory")
                return
            self._pending_checks[block.id] = command
            self.say(f"👑 🔍 $ {_short(command, 160)}")
        elif bee is None:
            if self.verbose:
                self.say(f"👑 🔧 {block.name} {_short(json.dumps(block.input, ensure_ascii=False), 100)}")
        elif self.verbose:
            target = block.input.get("file_path") or block.input.get("command") or block.input.get("pattern") or ""
            self.say(f"   🐝 {bee.label} · {block.name} {_short(target, 100)}")
            self.log.emit("bee_tool", label=bee.label, tool=block.name, target=str(target)[:300])

    def _user(self, message: UserMessage) -> None:
        if message.parent_tool_use_id or not isinstance(message.content, list):
            return
        for block in message.content:
            if not isinstance(block, ToolResultBlock):
                continue
            text = _result_text(block.content)
            if block.tool_use_id in self._pending_checks:
                command = self._pending_checks.pop(block.tool_use_id)
                ok = not block.is_error
                self.checks.append({"command": command, "ok": ok})
                tail = "\n".join(text.strip().splitlines()[-3:])
                self.say(f"   {'✅' if ok else '❌'} {_short(tail, 160) if tail else ''}")
                self.log.emit("check", command=command, ok=ok, output=text[-2000:])
            elif block.tool_use_id in self.dispatches:
                bee = self.dispatches[block.tool_use_id]
                if "async_launched" in text or "Async agent launched" in text:
                    bee.status = "launched"
                    continue
                bee.status = "failed" if block.is_error else "reported"
                self._report(block.tool_use_id, bee, text, ok=not block.is_error)

    def _report(self, tool_use_id: str, bee: Dispatch, text: str, ok: bool) -> None:
        clean = _TAG_RE.sub("", text)
        first = next((line for line in clean.splitlines() if line.strip() and not line.startswith("agentId")), "")
        self.say(f"   🐝 {bee.label} {'📨' if ok else '❌'} {_short(first, 150)}")
        self.log.emit("report", id=tool_use_id, label=bee.label, stage=bee.stage, ok=ok, text=clean[-4000:])

    @property
    def outstanding(self) -> list[Dispatch]:
        """Bees launched in the background whose report hasn't arrived yet."""
        return [d for d in self.dispatches.values() if d.status == "launched"]

    def _task_done(self, message: TaskNotificationMessage) -> None:
        bee = self.dispatches.get(message.tool_use_id or "")
        if not bee:
            return
        if bee.status == "launched":   # a background bee: its report comes with the notification
            self._report(message.tool_use_id, bee, message.summary or message.status, ok=message.status == "completed")
        bee.status = "reported" if message.status == "completed" else message.status
        self.log.emit("bee_done", id=message.tool_use_id, label=bee.label, status=message.status,
                      tokens=(message.usage or {}).get("total_tokens"), summary=message.summary)

    def _rate_limit(self, event: RateLimitEvent) -> None:
        info = event.rate_limit_info
        snapshot = {"ts": time.time(), "type": info.rate_limit_type, "status": info.status,
                    "utilization": info.utilization, "resets_at": info.resets_at}
        self.rate_limits.append(snapshot)
        self.log.emit("rate_limit", **snapshot)
        if info.status != "allowed":
            used = f"{info.utilization:.0%}" if info.utilization is not None else "?"
            self.say(f"⏳ usage limit {info.rate_limit_type}: {info.status} ({used} used)")

    # --- results -----------------------------------------------------------

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
