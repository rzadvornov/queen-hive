"""Run a hive session in OpenAI's Codex CLI, for GPT models.

The hive keeps its own Codex home (~/.hive/codex, as CODEX_HOME) so it never edits yours: the bees
are agent roles in agents/*.toml there, the hooks are its hooks.json, and the skills its skills/.
Your login and config.toml are linked in from your own Codex home. The Queen's instructions go in
per session as `developer_instructions`.
"""

import json
import os
import re
import shlex
import subprocess
import threading
from pathlib import Path

from hive import PLUGIN_DIR, memory, portable, providers
from hive.pricing import Tokens
from hivecore import brief_of_task

SHARED = ("auth.json", "config.toml")   # linked from your Codex home
SHELL_TOOLS = {"shell", "shell_command", "exec_command", "local_shell"}
APPROVAL = {"plan": "on-request", "auto": "never", "ask": "untrusted"}
READ_ONLY = {"scout"}
ENCRYPTED = re.compile(r"^gAAAA[\w=-]{20,}$")   # an encrypted message
SLACK = 5   # seconds: the Queen's rollout starts after the hive starts Codex, give or take the clock   # sandboxed read-only; reviewers may run tests, so the protect hook guards them instead

PREPARING = threading.Lock()   # `hive models --check` probes in parallel threads


def user_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def home() -> Path:
    return memory.hive_home() / "codex"


def env() -> dict[str, str]:
    return {"CODEX_HOME": str(home())}


def offered() -> list[tuple[str, str, str]]:
    """(slug, name, description) of the models your Codex account lists, best first, from Codex's
    models_cache.json; a ChatGPT plan offers its own set, not the API's."""
    for folder in (home(), user_home()):
        try:
            data = json.loads((folder / "models_cache.json").read_text())
        except (OSError, ValueError):
            continue
        listed = [m for m in data.get("models") or [] if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"]
        return [(m["slug"], m.get("display_name") or m["slug"], m.get("description") or "")
                for m in sorted(listed, key=lambda m: m.get("priority") or 0)]
    return []


def _toml(value) -> str:
    """A TOML value; JSON strings, numbers and booleans are valid TOML."""
    return json.dumps(value, ensure_ascii=False)


def prepare(bees: dict) -> Path:
    """The hive's Codex home with the bees on their models; returns it."""
    root = home()
    (root / "agents").mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        source, link = user_home() / name, root / name
        if source.exists() and not link.exists() and not link.is_symlink():
            link.symlink_to(source)
    for name in portable.BEES:
        description, instructions = portable.bee(name)
        model, settings = bees[name], portable.bee_settings(name)
        (root / "agents" / f"{name}.toml").write_text("\n".join([
            f"name = {_toml(name)}",
            f"description = {_toml(description)}",
            f"developer_instructions = {_toml(instructions)}",
            f"model = {_toml(model.id)}",
            f"model_reasoning_effort = {_toml(settings.get('effort', 'medium'))}",
            f"model_auto_compact_token_limit = {int(settings.get('autoCompactWindow', 100000))}",
            f"sandbox_mode = {_toml('read-only' if name in READ_ONLY else 'workspace-write')}",
        ]) + "\n")
    hook = lambda script: {"type": "command", "command": f"python3 {shlex.quote(str(PLUGIN_DIR / 'scripts' / script))}"}
    (root / "hooks.json").write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash|apply_patch", "hooks": [hook("protect.py")]},
                       {"matcher": "spawn_agent", "hooks": [hook("events.py")]}],
        "PostToolUse": [{"matcher": "Bash", "hooks": [hook("events.py")]}],
        "SubagentStop": [{"hooks": [hook("events.py")]}],
        "Stop": [{"hooks": [hook("events.py")]}],
    }}, indent=2))
    portable.export_skills(root / "skills")
    return root


def command(job, pdir: Path, system: str, session_id: str, headless: bool) -> tuple[list[str], dict]:
    """The `codex` command line and its environment. Codex picks its own session id."""
    prepare(job.bee_models())
    argv = [providers.binary("gpt")]
    if headless:
        argv += ["exec", "--json", "--skip-git-repo-check"]
    argv += ["--cd", str(job.folders[0])]
    for folder in [*job.folders[1:], pdir]:
        argv += ["--add-dir", str(folder)]
    approval = "never" if headless else APPROVAL.get(job.mode, "on-request")
    argv += ["--model", job.queen.id,
             "-c", f"developer_instructions={_toml(system)}",
             "-c", 'sandbox_mode="workspace-write"',
             "-c", f"approval_policy={_toml(approval)}",
             "-c", "agents.max_threads=5",
             "-c", "agents.max_depth=1"]
    if job.queen.queen_effort:
        argv += ["-c", f"model_reasoning_effort={_toml(job.queen.queen_effort)}"]
    if job.goal:
        argv += ["--", job.goal]
    return argv, env()


def failure(stdout: str, stderr: str, code: int) -> str | None:
    """Why a headless `codex exec --json` run failed, or None."""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "turn.failed":
            return f"turn failed: {(event.get('error') or {}).get('message', '')}"
        if event.get("type") == "error":
            return str(event.get("message", "error"))
    if code:
        tail = (stderr or stdout).strip().splitlines()
        return tail[-1] if tail else f"exit code {code}"
    return None


def probe(model) -> tuple[bool, str]:
    with PREPARING:
        prepare({name: model for name in portable.BEES})
    argv = [providers.binary("gpt"), "exec", "--json", "--skip-git-repo-check", "--model", model.id,
            "-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"', "--", "Reply with the single word OK."]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
                              env={**os.environ, **env()}, cwd=memory.hive_home())
    except subprocess.TimeoutExpired:
        return False, "timed out"
    error = failure(done.stdout, done.stderr, done.returncode)
    return (False, error[:200]) if error else (True, "")


def hooks_trusted() -> bool:
    """Whether you approved hooks in the hive's Codex home: Codex keeps that in its config.toml ([hooks.state])
    and runs no hook before it. Without them protected paths aren't guarded."""
    try:
        return "hooks.state" in (home() / "config.toml").read_text()
    except OSError:
        return False


TRUST_HINT = ("open Codex once in the hive's home and approve the hive's hooks: CODEX_HOME={home} codex")


def login_status() -> str:
    """`codex login status` as the hive's sessions see it."""
    try:
        done = subprocess.run([providers.binary("gpt"), "login", "status"], capture_output=True, text=True, timeout=30,
                              env={**os.environ, **env()})
    except (OSError, subprocess.TimeoutExpired, SystemExit) as error:
        return str(error)
    lines = (done.stdout + done.stderr).strip().splitlines()
    return lines[-1] if lines else "?"


# --- rollouts: Codex's session logs -------------------------------------------

def _lines(path: Path) -> list[dict]:
    entries = []
    try:
        text = path.read_text()
    except OSError:
        return entries
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _meta(path: Path) -> dict:
    try:
        with path.open() as handle:
            first = json.loads(handle.readline())
    except (OSError, ValueError):
        return {}
    return first.get("payload", {}) if first.get("type") == "session_meta" else {}


def _is_bee(meta: dict) -> bool:
    source = meta.get("source")
    return bool(meta.get("parent_thread_id")) or (isinstance(source, dict) and "subagent" in source)


def _ts(entry: dict) -> float | None:
    from hive.transcript import _ts as parse

    return parse(entry)


def rollouts(since: float) -> list[Path]:
    base = home() / "sessions"
    return sorted(p for p in base.glob("**/rollout-*.jsonl") if p.stat().st_mtime >= since - 60) if base.exists() else []


def locate(started: float, cwd: Path) -> Path | None:
    """The Queen's rollout: the first top-level session in this folder since the hive started Codex."""
    found = []
    for path in rollouts(started):
        meta = _meta(path)
        stamp = _ts({"timestamp": meta.get("timestamp")}) or path.stat().st_mtime
        if meta and not _is_bee(meta) and Path(meta.get("cwd") or "/").resolve() == cwd.resolve() and stamp >= started - SLACK:
            found.append((stamp, path))
    return min(found)[1] if found else None


class _Usage:
    """Tokens per model request, from the running totals in a rollout's token_count events."""

    def __init__(self, model: str):
        self.model, self.previous = model, {}

    def step(self, entry: dict) -> Tokens | None:
        payload = entry.get("payload") or {}
        if entry.get("type") == "turn_context" and payload.get("model"):
            self.model = payload["model"]
        if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
            return None
        total = (payload.get("info") or {}).get("total_token_usage") or {}
        delta = {k: int(total.get(k) or 0) - int(self.previous.get(k) or 0)
                 for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
        if total:
            self.previous = total
        if not any(v > 0 for v in delta.values()):
            return None   # the same totals again, e.g. a rate-limit update
        cached = max(delta["cached_input_tokens"], 0)
        return Tokens(input=max(delta["input_tokens"] - cached, 0), output=max(delta["output_tokens"], 0), cache_read=cached)


def _usage(entries: list[dict], model: str):
    usage = _Usage(model)
    for entry in entries:
        tokens = usage.step(entry)
        if tokens:
            yield _ts(entry), usage.model, tokens


def _args(payload: dict) -> dict:
    raw = payload.get("arguments") or payload.get("input") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {"command": raw}
    return raw if isinstance(raw, dict) else {}


def _shell(args: dict) -> str:
    command = args.get("command") or args.get("cmd") or ""
    if isinstance(command, list):
        command = command[2] if len(command) == 3 and command[1] in ("-lc", "-c") else shlex.join(command)
    return str(command)


def _exit_ok(output) -> bool:
    text = output if isinstance(output, str) else json.dumps(output)
    match = re.search(r'exit[_ ]code"?\s*[:=]?\s*(-?\d+)', text, re.I) or re.search(r"exited with code (-?\d+)", text, re.I)
    return match is None or match.group(1) == "0"


def _said(entry: dict, legacy: bool) -> tuple[str, str] | None:
    """("prompt" | "text", words) if the entry is the user's prompt or the model's reply. Older Codex logs
    them as user_message/agent_message events; newer ones only as messages, with their own context
    (<environment_context> …) as user messages too."""
    payload = entry.get("payload") or {}
    if legacy:
        if entry.get("type") == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
            return ("prompt" if payload["type"] == "user_message" else "text"), payload.get("message", "")
        return None
    if entry.get("type") != "response_item" or payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
        return None
    text = "\n".join(part.get("text", "") for part in payload.get("content") or []
                     if isinstance(part, dict) and part.get("type") in ("input_text", "output_text"))
    if payload["role"] == "user":
        return None if text.lstrip().startswith("<") else ("prompt", text)
    return "text", text


def _legacy(entries: list[dict]) -> bool:
    return any(e.get("type") == "event_msg" and (e.get("payload") or {}).get("type") == "user_message" for e in entries)


def events(entries: list[dict]) -> list[dict]:
    """A Queen's rollout as the event list transcript.from_events reads."""
    out, pending, legacy = [], {}, _legacy(entries)
    usage = _Usage((next((e for e in entries if e.get("type") == "session_meta"), {}).get("payload") or {}).get("model", ""))
    for entry in entries:
        payload, ts = entry.get("payload") or {}, _ts(entry)
        kind = payload.get("type")
        tokens = usage.step(entry)
        if tokens:
            out.append({"t": "usage", "model": usage.model, "tokens": tokens, "ts": ts})
        said = _said(entry, legacy)
        if said:
            out.append({"t": said[0], "text": said[1], "ts": ts})
        elif entry.get("type") == "response_item" and kind in ("function_call", "custom_tool_call"):
            name, args, call = payload.get("name"), _args(payload), payload.get("call_id")
            if name == "spawn_agent":
                message, task = str(args.get("message") or ""), args.get("task_name") or ""
                if ENCRYPTED.match(message) or not message:   # newer Codex encrypts the brief: its task name says what it was
                    message = brief_of_task(task)
                out.append({"t": "dispatch", "id": call, "agent": args.get("agent_type") or "default", "brief": message,
                            "task": args.get("task_name") or "", "ts": ts})
                pending[call] = "bee"
            elif name in SHELL_TOOLS:
                pending[call] = _shell(args)
        elif entry.get("type") == "response_item" and kind in ("function_call_output", "custom_tool_call_output"):
            call = payload.get("call_id")
            what = pending.pop(call, None)
            if what == "bee":
                out.append({"t": "dispatched", "id": call, "ok": "error" not in str(payload.get("output", ""))[:80].lower(),
                            "ts": ts})
            elif what:
                out.append({"t": "check", "command": what, "ok": _exit_ok(payload.get("output")), "ts": ts})
    return out


def _first_prompt(entries: list[dict]) -> str:
    legacy = _legacy(entries)
    return next((said[1] for said in map(lambda e: _said(e, legacy), entries) if said and said[0] == "prompt"), "")


def transcript(session_id: str, started: float, cwd: Path):
    """(job traces, exact cost, session id) of the session the hive started, or None if it can't be found."""
    from hive.transcript import from_events, match_brief

    path = locate(started, cwd)
    if not path:
        return None
    meta = _meta(path)
    main_id = meta.get("id") or path.stem
    entries = _lines(path)
    queen_events = events(entries)
    briefs = {e["id"]: (e["brief"], e["agent"]) for e in queen_events if e["t"] == "dispatch"}
    by_task = {e["task"]: (e["brief"], e["agent"]) for e in queen_events if e["t"] == "dispatch" and e.get("task")}
    bees = []
    for other in rollouts(started):
        bee_meta = _meta(other)
        if other == path or not _is_bee(bee_meta) or main_id not in (bee_meta.get("session_id"), bee_meta.get("parent_thread_id")):
            continue
        bee_entries = _lines(other)
        task = (bee_meta.get("agent_path") or "").rsplit("/", 1)[-1]   # a bee's brief arrives encrypted: match its task name
        brief, agent = by_task.get(task) or match_brief(_first_prompt(bee_entries), bee_meta.get("agent_role") or "", briefs)
        for ts, model, tokens in _usage(bee_entries, bee_meta.get("model", "")):
            bees.append((brief, agent, model, tokens, ts))
    return from_events(queen_events, bees, main_id), None, main_id
