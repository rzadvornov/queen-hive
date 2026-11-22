"""PreToolUse hook: deny edits to paths a project's hive profile marks as protected.

File tools are checked exactly. For Bash, a command is denied only when a protected
path is the *target* of a write: a redirect target (`> file`, `>> file`), or a path
argument of a writing command (rm, mv, cp destination, tee, touch, truncate, sed -i,
git rm/mv/checkout/restore). Reading or running protected files is allowed.

Scouts and reviewers are read-only: any file edit by them is denied, and so is a shell
write outside the temp folders. No bee may change the hive itself (its rules, bees, hooks and
skills): only the Queen does, when she applies a retro item you approved.

The same script guards Codex (apply_patch, Bash) and Gemini CLI sessions (write_file, replace,
run_shell_command; a BeforeTool event, answered with {"decision": "deny"}). The Gemini CLI doesn't
say which sub-agent calls a tool, so there the read-only bees rely on their tool lists.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

from hivecore import protecting_rule

FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path",
              "write_file": "file_path", "replace": "file_path"}
SHELL_TOOLS = {"Bash", "run_shell_command"}
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)
GEMINI = False   # set from the event name: Gemini expects another answer format
SEPARATORS = {";", "&&", "||", "|", "&"}
ALL_ARGS = {"rm", "mv", "tee", "touch", "truncate", "unlink", "rmdir", "shred", "chmod", "chown"}
GIT_WRITES = {"rm", "mv", "checkout", "restore"}
READ_ONLY_BEES = {"scout", "reviewer"}
# The hive's plugin: this copy, and the one `hive` loaded it from (a copy is used when a bee runs on another model).
HIVE_ROOTS = {Path(__file__).resolve().parent.parent,
              *([Path(os.environ["HIVE_CORE_DIR"]).resolve()] if os.environ.get("HIVE_CORE_DIR") else [])}
SCRATCH = ("/tmp/", "/private/tmp/", "/var/folders/", "/dev/null")
_REDIRECT = re.compile(r"^(\d*|&)>>?(.*)$")   # >, >>, 2>, &>, and attached forms like >file


def deny(reason: str) -> None:
    if GEMINI:
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)
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


def patch_targets(tool_input) -> list[str]:
    """Files a Codex apply_patch call adds, changes, deletes or moves to."""
    patch = tool_input.get("command") or tool_input.get("input") or tool_input.get("patch") or ""
    return _PATCH_FILE.findall(patch if isinstance(patch, str) else " ".join(map(str, patch)))


def shell_command(tool_input) -> str:
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    return shlex.join(command) if isinstance(command, list) else str(command)


def main() -> None:
    global GEMINI
    data = json.load(sys.stdin)
    GEMINI = data.get("hook_event_name") == "BeforeTool"
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or ".")
    edits = ([tool_input.get(FILE_TOOLS[tool])] if tool in FILE_TOOLS and tool_input.get(FILE_TOOLS[tool])
             else patch_targets(tool_input) if tool == "apply_patch" else [])

    bee = (data.get("agent_type") or "").rsplit(":", 1)[-1]
    if bee in READ_ONLY_BEES:
        if edits:
            deny(f"The Hive: the {bee} bee is read-only. Report what should change instead of changing it.")
        if tool in SHELL_TOOLS:
            for target in write_targets(shell_command(tool_input)):
                if not str(Path(target).expanduser()).startswith(SCRATCH):
                    deny(f"The Hive: the {bee} bee is read-only and may write only to temp folders, not to {target}.")

    # Unless the hive is the project itself: then its plugin is your code, which bees work on as usual.
    guarded = {root for root in HIVE_ROOTS if not (root == cwd.resolve() or cwd.resolve() in root.parents)}
    if bee and guarded:
        shell = write_targets(shell_command(tool_input)) if tool in SHELL_TOOLS else []
        for target in [*edits, *shell]:
            path = Path(target).expanduser()
            path = (path if path.is_absolute() else cwd / path).resolve()
            if any(path == root or root in path.parents for root in guarded):
                deny(f"The Hive: bees don't change the hive itself ({path.name}). Report what should change; "
                     "the Queen applies retro edits the user approves.")

    for target in edits:
        check_path(target, cwd)
    if tool in SHELL_TOOLS:
        for target in write_targets(shell_command(tool_input)):
            check_path(target, cwd)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Never block work because the guard itself failed.
        sys.exit(0)
