"""Which AI provider runs the hive: Claude (Claude Code), GPT (Codex CLI) or Gemini (Gemini CLI).

The choice is asked once and kept in ~/.hive/state.json. `hive provider` changes it, and
`--provider` overrides it for one run.
"""

import shutil
from dataclasses import dataclass
from types import ModuleType

from hive import memory


@dataclass(frozen=True)
class Provider:
    key: str
    name: str       # what the user picks: Claude, GPT, Gemini
    cli: str        # the executable
    product: str    # the CLI's name
    install: str
    login: str


PROVIDERS: dict[str, Provider] = {
    "claude": Provider("claude", "Claude", "claude", "Claude Code", "https://code.claude.com (or pip install -e \".[bundled]\")",
                       "claude, then /login (or set ANTHROPIC_API_KEY)"),
    "gpt": Provider("gpt", "GPT", "codex", "Codex CLI", "npm install -g @openai/codex",
                    "codex login (ChatGPT plan), or set OPENAI_API_KEY"),
    "gemini": Provider("gemini", "Gemini", "gemini", "Gemini CLI", "npm install -g @google/gemini-cli",
                       "set GEMINI_API_KEY (Google AI Studio), or Vertex AI credentials"),
}
DEFAULT = "claude"


def get(key: str) -> Provider:
    key = key.strip().lower()
    key = {"openai": "gpt", "chatgpt": "gpt", "codex": "gpt", "google": "gemini", "anthropic": "claude"}.get(key, key)
    if key not in PROVIDERS:
        raise SystemExit(f"unknown provider '{key}'. Known: {', '.join(PROVIDERS)}")
    return PROVIDERS[key]


def installed(key: str) -> bool:
    if key == "claude":   # Claude Code may also come bundled with the SDK
        from hive import claude

        try:
            claude.binary()
            return True
        except SystemExit:
            return False
    return shutil.which(PROVIDERS[key].cli) is not None


def saved() -> str | None:
    key = memory.load_state().get("provider")
    return key if key in PROVIDERS else None


def save(key: str) -> None:
    state = memory.load_state()
    state["provider"] = key
    memory.save_state(state)


def choose(default: str | None = None) -> str:
    """Ask which provider to use and remember the answer."""
    from hive import ui

    options = [(p.key, f"{p.name:7} {p.product}" + ("" if installed(p.key) else f"  (not installed: {p.install})"), True)
               for p in PROVIDERS.values()]
    key = ui.choose("🤖 Which AI should run the hive? (change it later with `hive provider`)", options,
                    default or saved() or DEFAULT)
    save(key)
    return key


def current(override: str | None = None, ask: bool = True) -> str:
    """The provider for this run: --provider, else the saved choice, else asked once (Claude without a terminal)."""
    from hive import ui

    if override:
        return get(override).key
    key = saved()
    if key:
        return key
    return choose() if ask and ui.interactive() else DEFAULT


def runtime(key: str) -> ModuleType:
    """The module that runs a session in the provider's CLI."""
    if key == "gpt":
        from hive import codex

        return codex
    if key == "gemini":
        from hive import gemini

        return gemini
    raise ValueError(f"{key} sessions run in hive.launch")


def binary(key: str) -> str:
    found = shutil.which(PROVIDERS[key].cli)
    if not found:
        p = PROVIDERS[key]
        raise SystemExit(f"{p.product} not found. Install it with `{p.install}`, then sign in: {p.login}. "
                         "Or switch provider with `hive provider`.")
    return found
