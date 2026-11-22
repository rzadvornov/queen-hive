"""Find and run Claude Code, the one runtime behind every hive session."""

import json
import shutil
import subprocess
from pathlib import Path


def binary() -> str:
    """Claude Code on PATH, else the copy bundled with the SDK (the optional `bundled` extra)."""
    found = shutil.which("claude")
    if found:
        return found
    try:
        import claude_agent_sdk
    except ImportError:
        claude_agent_sdk = None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude" if claude_agent_sdk else None
    if bundled and bundled.is_file():
        return str(bundled)
    raise SystemExit("Claude Code not found. Install it (https://code.claude.com), or install the hive with its own "
                     "copy: pip install -e \".[bundled]\"")


def print_mode(args: list[str], prompt: str, cwd: Path | None = None, env: dict | None = None,
               timeout: float | None = None) -> dict:
    """Run `claude -p` to the end and return its JSON result; failures come back as is_error results."""
    argv = [binary(), "-p", "--output-format", "json", "--permission-prompts", "none", *args, "--", prompt]
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"is_error": True, "subtype": "timeout", "result": f"timed out after {timeout}s"}
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        error = (done.stderr or done.stdout).strip().splitlines()
        return {"is_error": True, "subtype": "no_result", "result": error[-1] if error else f"exit code {done.returncode}"}


HIVE_PLUGIN_NAMES = ("queen-hive", "haiku-hive")   # haiku-hive: its name before 0.2, maybe still installed


def installed_plugins(*names: str) -> list[str]:
    """Enabled installed plugins with one of these names, e.g. ["queen-hive@hive-local"]."""
    try:
        done = subprocess.run([binary(), "plugin", "list", "--json"], capture_output=True, text=True, timeout=30)
        plugins = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [p["id"] for p in plugins if isinstance(p, dict) and p.get("enabled") and p.get("id", "").split("@")[0] in names]
