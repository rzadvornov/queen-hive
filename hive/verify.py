"""Objective pass/fail: the hive itself runs the acceptance commands after a job."""

import re
import subprocess
from pathlib import Path


def run_checks(commands: list[str], cwd: Path, timeout: int = 900) -> list[dict]:
    results = []
    for command in commands:
        try:
            out = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            output = (out.stdout + out.stderr).strip()
            results.append({"command": command, "ok": out.returncode == 0, "code": out.returncode,
                            "tail": "\n".join(output.splitlines()[-15:])})
        except subprocess.TimeoutExpired:
            results.append({"command": command, "ok": False, "code": None, "tail": f"timed out after {timeout}s"})
    return results


def passed(results: list[dict]) -> bool | None:
    return all(r["ok"] for r in results) if results else None


def acceptance_commands(explicit: list[str], summary: dict | None, profile_commands: dict[str, str]) -> list[str]:
    """--done wins; then the Queen's final checks; then the profile's test command."""
    if explicit:
        return explicit
    from_queen = [c for c in (summary or {}).get("done_when", []) if isinstance(c, str) and c.strip() and "<" not in c]
    if from_queen:
        return list(dict.fromkeys(from_queen))
    return [profile_commands["test"]] if profile_commands.get("test") else []


def parse_summary(text: str) -> dict | None:
    import json

    match = re.search(r"```hive-summary\s*\n(.*?)```", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def strip_summary(text: str) -> str:
    return re.sub(r"```hive-summary\s*\n.*?```", "", text or "", flags=re.S).strip()
