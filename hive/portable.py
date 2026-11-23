"""The plugin's content (Queen rules, bees, skills) in the form Codex and the Gemini CLI read.

The Claude Code plugin stays the one source: a retro edits rules/queen.md and agents/<name>.md
there, and every provider's session is built from them.
"""

import re
import shutil
from pathlib import Path

from hive import CORE_DIR

BEES = ("scout", "builder", "reviewer")
# What a retro edits once you approve an item. Interactive Codex and Gemini sessions may write here (Claude Code
# asks instead); the hook scripts next to them stay out of reach.
RETRO_FOLDERS = (CORE_DIR / "rules", CORE_DIR / "agents")
ICONS = {"scout": "🔎", "builder": "🔨", "reviewer": "🧐"}


def display_name(bee: str) -> str:
    """How a CLI that shows bee names shows this one: "🔎 Scout bee"."""
    return f"{ICONS[bee]} {bee.capitalize()} bee"

DISPATCH = {
    "gpt": """Dispatch them with the `spawn_agent` tool. Set `agent_type` to one of these roles:
- `scout`: read-only research in code, files and on the web.
- `builder`: makes changes (edits files, runs commands) for one brief.
- `reviewer`: independent review from one lens. Never edits.
Use only these three roles, never the built-in ones.

The first line of every brief (the `message`) is a brief ID, then a few words, and `task_name` is the same in
lowercase with underscores (`s1_auth_entry_points`):
`S1 find auth entry points`, `B2 add promo module`, `R-arch review structure`, `F1 fix rounding`.""",
    "gemini": """Dispatch them with the `invoke_agent` tool. Set `agent_name` to one of these sub-agents and `prompt` to the brief:
- `scout`: read-only research in code, files and on the web.
- `builder`: makes changes (edits files, runs commands) for one brief.
- `reviewer`: independent review from one lens. Never edits.
Use only these three sub-agents, never the built-in ones.

The first line of every brief (the `prompt`) is a brief ID, then a few words:
`S1 find auth entry points`, `B2 add promo module`, `R-arch review structure`, `F1 fix rounding`.""",
}


_FULL_REVIEW = re.compile(r"<!-- full-review -->\n.*?<!-- /full-review -->\n", re.S)


def rules_for(provider: str, review: str = "full") -> str:
    """rules/queen.md, with the dispatch instructions of the provider's CLI. Without a full review, the parts only a
    full review needs are left out: a shorter rule set is cheaper on every turn."""
    rules = (CORE_DIR / "rules" / "queen.md").read_text()
    rules = rules.replace("<!-- full-review -->\n", "").replace("<!-- /full-review -->\n", "") if review == "full" \
        else _FULL_REVIEW.sub("", rules)
    if provider == "claude":
        return rules
    rules = rules.replace("They run on Haiku unless your instructions name another model for a bee.",
                          "They run on a cheaper model, named in your instructions.")
    rules = re.sub(r"(## Your bees\n).*?(\n- S = scout)", lambda m: m.group(1) + DISPATCH[provider] + m.group(2),
                   rules, count=1, flags=re.S)
    return plain(rules)


def plain(text: str) -> str:
    """Claude Code plugin names → the names the other CLIs use (`queen-hive:scout` → `scout`)."""
    return re.sub(r"`queen-hive:([a-z-]+)`", r"`\1`", text).replace("${CLAUDE_PLUGIN_ROOT}", str(CORE_DIR))


def bee(name: str) -> tuple[str, str]:
    """(description, instructions) of a bee, from agents/<name>.md."""
    text = (CORE_DIR / "agents" / f"{name}.md").read_text()
    _, front, body = text.split("---", 2)
    description = next((line.split(":", 1)[1].strip() for line in front.splitlines() if line.startswith("description:")), name)
    return description, plain(body.strip())


def bee_settings(name: str) -> dict[str, str]:
    """The frontmatter of agents/<name>.md (effort, autoCompactWindow …): the Haiku bees' settings,
    which the other CLIs' bees get too."""
    _, front, _ = (CORE_DIR / "agents" / f"{name}.md").read_text().split("---", 2)
    return {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in front.splitlines()) if value}


def export_skills(dest: Path) -> None:
    """Copy the plugin's skills to a CLI's skills folder, with paths and bee names it understands."""
    dest.mkdir(parents=True, exist_ok=True)
    for skill in sorted((CORE_DIR / "skills").glob("*/SKILL.md")):
        target = dest / skill.parent.name
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir()
        (target / "SKILL.md").write_text(plain(skill.read_text()))
