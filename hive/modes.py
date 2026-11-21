"""Autonomy modes and the Claude Code permission settings behind each one."""

from dataclasses import dataclass, field
from pathlib import Path

from hive import ui

MODES = {
    "plan": "Plan first: the Queen shows her briefs, you approve, then the hive works on its own",
    "auto": "Fully autonomous: edits and commands run without asking, inside the granted folders",
    "ask": "Ask for risky actions: edits are automatic, other commands, web access and outside paths ask you",
}
DEFAULT_MODE = "plan"

BASE_TOOLS = ["Agent", "Task", "Read", "Glob", "Grep", "TodoWrite", "Skill", "ToolSearch"]
# File edits are deliberately absent: acceptEdits approves them inside the granted folders,
# and Claude Code asks before edits anywhere else.
WORK_TOOLS = ["Bash", "WebSearch", "WebFetch"]
SAFE_BASH = ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(ls:*)", "Bash(python3 *changes.py diff:*)"]


def choose_mode(default: str | None = None) -> str:
    from hive import memory

    options = [(key, f"{key:5} {text}", True) for key, text in MODES.items()]
    return ui.choose("🛡  Choose the autonomy mode:", options,
                     default or memory.load_state().get("last_mode") or DEFAULT_MODE)


@dataclass
class Policy:
    """Permission settings for one Claude Code session."""

    mode: str
    folders: list[Path]
    commands: dict[str, str] = field(default_factory=dict)

    @property
    def permission_mode(self) -> str:
        return "plan" if self.mode == "plan" else "acceptEdits"

    @property
    def allowed_tools(self) -> list[str]:
        if self.mode == "ask":
            return BASE_TOOLS + SAFE_BASH + [f"Bash({cmd})" for cmd in self.commands.values()]
        return BASE_TOOLS + WORK_TOOLS
