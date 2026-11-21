"""Autonomy modes and the permission policy behind each one."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, PermissionUpdate

from hive import PLUGIN_DIR, ui

MODES = {
    "plan": "Plan first: the Queen shows her briefs, you approve, then the hive works on its own",
    "auto": "Fully autonomous: edits and commands run without asking, inside the granted folders",
    "ask": "Ask for risky actions: edits are automatic, other commands, web access and outside paths ask you",
}
DEFAULT_MODE = "plan"

FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
BASE_TOOLS = ["Agent", "Task", "Read", "Glob", "Grep", "TodoWrite", "Skill", "ToolSearch"]
# File edits are deliberately absent: acceptEdits approves them inside the granted folders,
# and edits anywhere else fall through to can_use_tool.
WORK_TOOLS = ["Bash", "WebSearch", "WebFetch"]
SAFE_BASH = ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(ls:*)", "Bash(python3 *changes.py diff:*)"]


def choose_mode(default: str | None = None) -> str:
    from hive import memory

    options = [(key, f"{key:5} {text}", True) for key, text in MODES.items()]
    return ui.choose("🛡  Choose the autonomy mode:", options,
                     default or memory.load_state().get("last_mode") or DEFAULT_MODE)


def _inside(path: str, folders: list[Path], cwd: Path) -> bool:
    target = Path(path).expanduser()
    target = (target if target.is_absolute() else cwd / target).resolve()
    return any(target == f or f in target.parents for f in folders)


def _describe(tool: str, data: dict, context: Any) -> str:
    who = "🐝 a bee" if getattr(context, "agent_id", None) else "👑 the Queen"
    if tool == "Bash":
        return f"{who} wants to run: {data.get('command', '')}"
    if tool in FILE_TOOLS:
        return f"{who} wants to {tool.lower()} {data.get(FILE_TOOLS[tool], '')}"
    if tool in ("WebFetch", "WebSearch"):
        return f"{who} wants web access: {data.get('url') or data.get('query', '')}"
    return f"{who} wants to use {tool}: {str(data)[:120]}"


@dataclass
class Policy:
    """Permission settings for one session, plus the can_use_tool callback."""

    mode: str
    folders: list[Path]
    commands: dict[str, str] = field(default_factory=dict)
    approved_plan: str | None = None
    retro: bool = False   # a retro may edit the hive's own rules and bees in PLUGIN_DIR
    _always: set[str] = field(default_factory=set)

    @property
    def permission_mode(self) -> str:
        return "plan" if self.mode == "plan" else "acceptEdits"

    @property
    def allowed_tools(self) -> list[str]:
        if self.mode == "ask":
            return BASE_TOOLS + SAFE_BASH + [f"Bash({cmd})" for cmd in self.commands.values()]
        return BASE_TOOLS + WORK_TOOLS

    async def can_use_tool(self, tool: str, data: dict, context: Any):
        cwd = self.folders[0]
        if tool == "ExitPlanMode":
            return await self._review_plan(data)
        folders = [*self.folders, PLUGIN_DIR] if self.retro else self.folders
        if tool in FILE_TOOLS and not _inside(data.get(FILE_TOOLS[tool], ""), folders, cwd):
            if self.mode != "ask":
                return PermissionResultDeny(message="Outside the folders granted to the hive. Ask the user to add it with -d.")
            return await self._ask(tool, data, context)
        if self.mode == "ask":
            return await self._ask(tool, data, context)
        return PermissionResultAllow()

    async def _ask(self, tool: str, data: dict, context: Any):
        key = f"{tool}:{data.get('command') or data.get('url') or data.get('query') or ''}"
        if key in self._always or tool in self._always:
            return PermissionResultAllow()
        if not ui.interactive():
            return PermissionResultDeny(message="The user is not available to approve this. Find another way or report it.")
        answer = (await ui.ask_async(f"\n❓ {_describe(tool, data, context)}\n   allow? [y]es / [n]o / [a]lways this session: ")).strip().lower()
        if answer in ("a", "always"):
            self._always.add(key if tool == "Bash" else tool)
            return PermissionResultAllow()
        if answer in ("y", "yes", "д", "да"):
            return PermissionResultAllow()
        reason = (await ui.ask_async("   reason for the Queen (optional): ")).strip()
        return PermissionResultDeny(message=f"The user declined. {reason}".strip())

    async def _review_plan(self, data: dict):
        plan = data.get("plan", "")
        print("\n" + "─" * 60 + "\n👑 The Queen's plan\n" + "─" * 60 + f"\n{plan}\n" + "─" * 60)
        if not ui.interactive():
            return PermissionResultDeny(message="No user available to approve the plan.", interrupt=True)
        while True:
            answer = (await ui.ask_async("[a]pprove / [e]dit (give feedback) / [c]ancel: ")).strip().lower()
            if answer in ("a", "approve", "y", "yes", ""):
                self.approved_plan = plan
                return PermissionResultAllow(
                    updated_permissions=[PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")]
                )
            if answer in ("e", "edit"):
                feedback = (await ui.ask_async("   your feedback: ")).strip()
                return PermissionResultDeny(message=f"Revise the plan. User feedback: {feedback}")
            if answer in ("c", "cancel"):
                return PermissionResultDeny(message="The user cancelled the task.", interrupt=True)
