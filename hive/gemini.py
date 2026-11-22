"""Run a hive session in Google's Gemini CLI, for Gemini models.

The hive keeps its own Gemini home (~/.hive/gemini, as GEMINI_CLI_HOME) so it never edits yours:
the Queen's instructions are its GEMINI.md, the bees are sub-agents in agents/*.md, the hooks sit in
its settings.json and the skills in skills/. Your login files and settings are carried over from
your own ~/.gemini.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

from hive import CORE_DIR, memory, portable, providers
from hive.pricing import Tokens

SHARED = ("oauth_creds.json", "google_accounts.json", "installation_id", ".env")   # linked from ~/.gemini
APPROVAL = {"plan": "auto_edit", "auto": "yolo", "ask": "default"}
READ = ["read_file", "read_many_files", "glob", "grep_search", "list_directory"]
TOOLS = {
    "scout": [*READ, "web_fetch", "google_web_search"],
    "builder": [*READ, "write_file", "replace", "run_shell_command"],
    "reviewer": [*READ, "run_shell_command", "web_fetch"],
}
BEE_LIMITS = {"max_turns": 100, "timeout_mins": 30}   # the CLI's defaults (30 turns, 10 minutes) cut builders off
BEE_TOOLS = ("invoke_agent", *portable.BEES)
INJECTED = ("<session_context>",)   # user messages the CLI writes itself   # sub-agents: one invoke_agent tool, or a tool per agent in older CLIs

PREPARING = threading.Lock()   # `hive models --check` probes in parallel threads


def user_dir() -> Path:
    return Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()).expanduser() / ".gemini"


def home() -> Path:
    return memory.hive_home() / "gemini"


def config_dir() -> Path:
    return home() / ".gemini"


def env(root: Path | None = None) -> dict[str, str]:
    return {"GEMINI_CLI_HOME": str(root or home())}


def session_home(session_id: str) -> Path:
    """A session's own Gemini home: GEMINI.md holds that session's Queen instructions, so two sessions
    at once must not share one. Its chat logs go to the shared tmp/, where `locate` finds them."""
    return home() / "sessions" / session_id


def _prune(keep_days: float = 14) -> None:   # long enough not to hit a session still open
    cutoff = time.time() - keep_days * 86400
    for old in (home() / "sessions").glob("*") if (home() / "sessions").exists() else []:
        if old.is_dir() and old.stat().st_mtime < cutoff:
            shutil.rmtree(old, ignore_errors=True)


def settings() -> dict:
    """Your Gemini settings, with the hive's hooks added."""
    try:
        data = json.loads((user_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    auth = data.setdefault("security", {}).setdefault("auth", {})
    if os.environ.get("GEMINI_API_KEY") and auth.get("selectedType") in (None, "oauth-personal"):
        auth["selectedType"] = "gemini-api-key"   # Google no longer serves personal logins to the CLI
    hook = lambda script, name: {"type": "command", "name": name,
                                 "command": f"python3 {shlex.quote(str(CORE_DIR / 'scripts' / script))}"}
    bees = "|".join(BEE_TOOLS)
    ours = {
        "BeforeTool": [{"matcher": "write_file|replace|run_shell_command", "hooks": [hook("protect.py", "hive-protect")]},
                       {"matcher": bees, "hooks": [hook("events.py", "hive-events")]}],
        "AfterTool": [{"matcher": f"{bees}|run_shell_command", "hooks": [hook("events.py", "hive-events")]}],
        "AfterAgent": [{"hooks": [hook("events.py", "hive-events")]}],
    }
    hooks = data.setdefault("hooks", {})
    for event, groups in ours.items():
        hooks[event] = [*(hooks.get(event) or []), *groups]
    # Sub-agents run under their own name as the override scope: give each bee its effort as a thinking level.
    configs = data.setdefault("modelConfigs", {})
    configs["customOverrides"] = [*(configs.get("customOverrides") or []), *(
        {"match": {"overrideScope": name}, "modelConfig": {"generateContentConfig": {"thinkingConfig": {
            "thinkingLevel": portable.bee_settings(name).get("effort", "medium").upper()}}}} for name in portable.BEES)]
    data.setdefault("hooksConfig", {})["enabled"] = True
    data.setdefault("experimental", {})["enableAgents"] = True
    return data


def prepare(bees: dict, system: str = "", root: Path | None = None) -> Path:
    """A Gemini config folder (default: the hive's shared one) with the Queen's instructions and the bees
    on their models; returns it."""
    root = root or config_dir()
    (root / "agents").mkdir(parents=True, exist_ok=True)
    if root != config_dir():   # chat logs stay in one place
        (config_dir() / "tmp").mkdir(parents=True, exist_ok=True)
        if not (root / "tmp").is_symlink():
            (root / "tmp").symlink_to(config_dir() / "tmp")
    for name in SHARED:
        source, link = user_dir() / name, root / name
        if source.exists() and not link.exists() and not link.is_symlink():
            link.symlink_to(source)
    (root / "settings.json").write_text(json.dumps(settings(), indent=2))
    (root / "GEMINI.md").write_text(system)
    for name in portable.BEES:
        description, instructions = portable.bee(name)
        tools = "\n".join(f"  - {tool}" for tool in TOOLS[name])
        (root / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndisplay_name: {json.dumps(portable.display_name(name), ensure_ascii=False)}\n"
            f"description: {json.dumps(description)}\nkind: local\ntools:\n{tools}\n"
            f"model: {bees[name].id}\n" + "".join(f"{key}: {value}\n" for key, value in BEE_LIMITS.items())
            + f"---\n\n{instructions}\n")
    portable.export_skills(root / "skills")
    return root


def command(job, pdir: Path, system: str, session_id: str, headless: bool) -> tuple[list[str], dict]:
    _prune()
    own = session_home(session_id)
    prepare(job.bee_models(), system, own / ".gemini")
    # Headless runs keep the mode's approval: the CLI's print mode leaves out the tools that would need it.
    argv = [providers.binary("gemini"), "--model", job.queen.id, "--session-id", session_id, "--skip-trust",
            "--approval-mode", APPROVAL.get(job.mode, "auto_edit"),
            "--include-directories", ",".join(map(str, [*job.folders[1:], pdir, *(() if headless else portable.RETRO_FOLDERS)]))]
    if job.sandbox:
        argv.append("--sandbox")
    if headless:
        argv += ["--output-format", "json", "--prompt", job.goal]
    elif job.goal:
        argv += ["--prompt-interactive", job.goal]
    return argv, env(own)


def _json(text: str) -> dict:
    """The JSON result: the last top-level object in the output (on errors it follows log lines, on stderr)."""
    start = 0 if text.lstrip().startswith("{") else text.rfind("\n{") + 1
    try:
        data = json.loads(text[start:]) if "{" in text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _message(error) -> str:
    """The innermost readable message: API errors arrive as JSON inside JSON inside a message."""
    text = str(error.get("message") if isinstance(error, dict) else error)
    found = re.findall(r'message\\*"\s*:\s*\\*"([^"\\{][^"\\]*)', text)
    return found[-1] if found else text


SIGN_IN_HINT = " · set GEMINI_API_KEY (a key from Google AI Studio): Google doesn't serve the CLI to personal logins"


def failure(stdout: str, stderr: str, code: int) -> str | None:
    """Why a headless `gemini -p -o json` run failed, or None; a sign-in failure says what to do."""
    error = _json(stdout).get("error") or _json(stderr).get("error")
    if error:
        message = _message(error)
    elif code:
        lines = [line for line in (stderr or stdout).strip().splitlines() if line.strip()]
        message = next((line for line in lines if "Error" in line), lines[-1] if lines else f"exit code {code}")
    else:
        return None
    return message + (SIGN_IN_HINT if re.search(r"IneligibleTier|authenticat|API key", message, re.I) else "")


def probe(model) -> tuple[bool, str]:
    with PREPARING:
        prepare({name: model for name in portable.BEES})
    argv = [providers.binary("gemini"), "--model", model.id, "--skip-trust", "--approval-mode", "plan",
            "--output-format", "json", "--prompt", "Reply with the single word OK."]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
                              env={**os.environ, **env()}, cwd=memory.hive_home())
    except subprocess.TimeoutExpired:
        return False, "timed out"
    error = failure(done.stdout, done.stderr, done.returncode)
    if error and SIGN_IN_HINT in error:   # keep the hint when the message is cut
        error = error.replace(SIGN_IN_HINT, "")[:200 - len(SIGN_IN_HINT)] + SIGN_IN_HINT
    return (False, error[:300]) if error else (True, "")


# --- chat records: the Gemini CLI's session logs --------------------------------

def locate(session_id: str) -> Path | None:
    found = sorted((config_dir() / "tmp").glob(f"*/chats/session-*-{session_id[:8]}.jsonl"))
    return next((p for p in found if _records(p)[0].get("sessionId") == session_id), None)


def _records(path: Path) -> tuple[dict, list[dict]]:
    """(metadata, messages): each message once, as last written (a message is rewritten as it grows),
    without the ones a rewind took back."""
    meta, messages = {}, {}
    try:
        text = path.read_text()
    except OSError:
        return meta, []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if "sessionId" in record and "type" not in record:
            meta.update(record)
        elif record.get("$rewindTo") in messages:   # back to before that message
            ids = list(messages)
            for gone in ids[ids.index(record["$rewindTo"]):]:
                del messages[gone]
        elif record.get("id") and record.get("type"):
            messages[record["id"]] = record
    return meta, list(messages.values())


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _tokens(message: dict) -> Tokens | None:
    tokens = message.get("tokens")
    if not isinstance(tokens, dict):
        return None
    cached = int(tokens.get("cached") or 0)
    return Tokens(input=max(int(tokens.get("input") or 0) - cached, 0),
                  output=int(tokens.get("output") or 0) + int(tokens.get("thoughts") or 0), cache_read=cached)


def _ok(call: dict) -> bool:
    if call.get("status") not in (None, "success"):
        return False
    match = re.search(r"Exit Code: (-?\d+)", json.dumps(call.get("result") or call.get("resultDisplay") or ""))
    return match is None or match.group(1) == "0"


def events(messages: list[dict]) -> list[dict]:
    from hive.transcript import _ts

    out = []
    for message in messages:
        ts = _ts(message)
        if message.get("type") == "user":
            text = _text(message.get("content"))
            if not text.lstrip().startswith(INJECTED):
                out.append({"t": "prompt", "text": text, "ts": ts})
            continue
        if message.get("type") != "gemini":
            continue
        tokens = _tokens(message)
        if tokens:
            out.append({"t": "usage", "model": message.get("model") or "", "tokens": tokens, "ts": ts})
        for call in message.get("toolCalls") or []:
            name, args = call.get("name"), call.get("args") or {}
            if name in BEE_TOOLS:
                agent = args.get("agent_name") if name == "invoke_agent" else name
                brief = args.get("prompt") or args.get("query") or ""
                out.append({"t": "dispatch", "id": call.get("id"), "agent": agent or "?", "brief": str(brief), "ts": ts})
                out.append({"t": "dispatched", "id": call.get("id"), "ok": _ok(call), "ts": ts})
            elif name == "run_shell_command":
                out.append({"t": "check", "command": str(args.get("command", "")), "ok": _ok(call), "ts": ts})
        text = _text(message.get("content"))
        if text.strip():
            out.append({"t": "text", "text": text, "ts": ts})
    return out


def transcript(session_id: str, started: float, cwd: Path):
    """(job traces, exact cost, session id) of the session, or None if it can't be found."""
    from hive.transcript import _ts, from_events, match_brief

    path = locate(session_id)
    if not path:
        return None
    queen_events = events(_records(path)[1])
    briefs = {e["id"]: (e["brief"], e["agent"]) for e in queen_events if e["t"] == "dispatch"}
    bees = []
    for bee_file in sorted((path.parent / session_id).glob("*.jsonl")):
        messages = _records(bee_file)[1]
        prompt = next((_text(m.get("content")) for m in messages
                       if m.get("type") == "user" and not _text(m.get("content")).lstrip().startswith(INJECTED)), "")
        brief, agent = match_brief(prompt, "", briefs)
        for message in messages:
            tokens = _tokens(message) if message.get("type") == "gemini" else None
            if tokens:
                bees.append((brief, agent, message.get("model") or "", tokens, _ts(message)))
    return from_events(queen_events, bees, session_id), None, session_id
