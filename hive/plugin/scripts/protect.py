"""PreToolUse hook: deny edits to paths a project's hive profile marks as protected.

File tools are checked exactly. For Bash, a command is denied only when a protected
path is the *target* of a write: a redirect target (`> file`, `>> file`), or a path
argument of a writing command (rm, mv, cp destination, tee, touch, truncate, sed -i,
git rm/mv/checkout/restore). Reading or running protected files is allowed.
"""

import json
import re
import shlex
import sys
from pathlib import Path

from hivecore import protecting_rule

FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SEPARATORS = {";", "&&", "||", "|", "&"}
ALL_ARGS = {"rm", "mv", "tee", "touch", "truncate", "unlink", "rmdir", "shred", "chmod", "chown"}
GIT_WRITES = {"rm", "mv", "checkout", "restore"}
_REDIRECT = re.compile(r"^(\d*|&)>>?(.*)$")   # >, >>, 2>, &>, and attached forms like >file


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def check_path(raw: str, cwd: Path) -> None:
    if not raw or raw.startswith("-") or raw.startswith("&") or raw == "/dev/null":
        return
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    rule = protecting_rule(path)
    if rule:
        root, pattern = rule
        deny(f"The Hive: '{pattern}' is a protected path in {root}. It must not be changed "
             "(reading and running it is fine).")


def segments(words: list[str]) -> list[list[str]]:
    result, current = [], []
    for word in words:
        if word in SEPARATORS:
            result.append(current)
            current = []
        else:
            current.append(word)
    result.append(current)
    return [s for s in result if s]


def write_targets(command: str) -> list[str]:
    """Paths a shell command would write to, as far as a simple parse can tell."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        words = command.split()

    targets: list[str] = []
    for seg in segments(words):
        args: list[str] = []
        i = 0
        while i < len(seg):
            word = seg[i]
            redirect = _REDIRECT.match(word)
            if redirect and not word.startswith("<"):
                rest = redirect.group(2)
                if rest:
                    targets.append(rest)
                elif i + 1 < len(seg):
                    targets.append(seg[i + 1])
                    i += 1
            else:
                args.append(word)
            i += 1
        if not args:
            continue
        name = Path(args[0]).name
        operands = [a for a in args[1:] if not a.startswith("-")]
        if name in ALL_ARGS:
            targets += operands
        elif name == "cp" and operands:
            targets.append(operands[-1])
        elif name in ("sed", "perl") and any(a.startswith("-i") or a.startswith("-pi") for a in args[1:]):
            targets += operands[1:]
        elif name == "git" and operands and operands[0] in GIT_WRITES:
            targets += operands[1:]
    return targets


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or ".")

    if tool in FILE_TOOLS and tool_input.get(FILE_TOOLS[tool]):
        check_path(tool_input[FILE_TOOLS[tool]], cwd)
    elif tool == "Bash":
        for target in write_targets(tool_input.get("command", "")):
            check_path(target, cwd)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Never block work because the guard itself failed.
        sys.exit(0)
