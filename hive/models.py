"""Model catalog: who can be Queen, what each model costs, and access checks."""

import asyncio
import time
from dataclasses import dataclass

from hive import memory

PRICES_AS_OF = "2026-10-06"


@dataclass(frozen=True)
class Model:
    key: str            # short name used on the command line, e.g. "opus-5.5"
    id: str             # API model ID
    name: str
    input: float        # USD per million tokens
    output: float
    cache_read: float
    queen_effort: str | None = None   # None: not offered as Queen
    note: str = ""

    def cache_write(self, ttl: str = "1h") -> float:
        """Cache writes cost 2x input for the 1-hour TTL (main sessions), 1.25x for 5 minutes (subagents)."""
        return self.input * (2.0 if ttl == "1h" else 1.25)


CATALOG: tuple[Model, ...] = (
    Model("fable-5.1", "claude-fable-5-1", "Claude Fable 5.1", 10.0, 50.0, 0.25, "xhigh", "most capable"),
    Model("mythos-5.1", "claude-mythos-5-1", "Claude Mythos 5.1", 10.0, 50.0, 1.0, "xhigh", "Project Glasswing only"),
    Model("opus-5.5", "claude-opus-5-5", "Claude Opus 5.5", 4.0, 20.0, 0.20, "xhigh", "default Queen"),
    Model("sonnet-5.5", "claude-sonnet-5-5", "Claude Sonnet 5.5", 2.0, 10.0, 0.20, "high", "fast and cheap"),
    Model("opus-5", "claude-opus-5", "Claude Opus 5", 5.0, 25.0, 0.50, "xhigh"),
    Model("opus-4.8", "claude-opus-4-8", "Claude Opus 4.8", 5.0, 25.0, 0.50, "xhigh"),
    Model("haiku-5.5", "claude-haiku-5-5", "Claude Haiku 5.5", 0.10, 0.50, 0.01, None, "worker bees"),
)

DEFAULT_QUEEN = "opus-5.5"
DEFAULT_WORKERS = "haiku-5.5"
DEFAULT_COMPARE = ("sonnet-5.5", "opus-4.8", "opus-5.5")


def get(name: str) -> Model:
    """Look up a model by short key, API ID, or an ID with a suffix like '[1m]' or a date."""
    name = name.strip().lower()
    for model in CATALOG:
        if name in (model.key, model.id):
            return model
    for model in sorted(CATALOG, key=lambda m: -len(m.id)):
        if name.startswith(model.id):
            return model
    raise KeyError(f"unknown model '{name}'. Known: {', '.join(m.key for m in CATALOG)}")


def find(model_id: str) -> Model | None:
    try:
        return get(model_id)
    except KeyError:
        return None


def queens() -> list[Model]:
    return [m for m in CATALOG if m.queen_effort]


def access(state: dict) -> dict[str, dict]:
    return state.setdefault("access", {})


def is_available(state: dict, model: Model) -> bool | None:
    """True / False from the last check, None if never checked."""
    entry = access(state).get(model.key)
    return None if entry is None else bool(entry.get("ok"))


async def probe(model: Model) -> tuple[bool, str]:
    """Send a tiny request to see whether the current login can use this model."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        model=model.id,
        system_prompt="Reply with the single word OK.",
        tools=[],
        max_turns=1,
        setting_sources=[],
        env={"CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1"},
    )
    served = ""
    try:
        async for message in query(prompt="OK?", options=options):
            if isinstance(message, AssistantMessage):
                if message.error:
                    return False, message.error
                served = served or message.model
            elif isinstance(message, ResultMessage) and message.is_error:
                return False, (message.result or message.subtype or "error")[:200]
    except Exception as error:  # noqa: BLE001 - any failure means "no access"
        return False, str(error).splitlines()[0][:200] if str(error) else type(error).__name__
    if served and not served.startswith(model.id):
        return False, f"served by {served} instead"
    return True, ""


async def check_access(keys: list[str] | None = None) -> dict[str, dict]:
    """Probe models concurrently and cache the result in ~/.hive/state.json."""
    chosen = [get(k) for k in keys] if keys else [m for m in CATALOG if m.queen_effort or m.key == DEFAULT_WORKERS]
    results = await asyncio.gather(*(probe(m) for m in chosen))
    state = memory.load_state()
    now = int(time.time())
    for model, (ok, error) in zip(chosen, results):
        access(state)[model.key] = {"ok": ok, "error": error, "checked_at": now}
    memory.save_state(state)
    return {m.key: access(state)[m.key] for m in chosen}


def _menu(candidates: list[Model], state: dict) -> list[tuple[str, str, bool]]:
    """Menu options; models known to be unavailable are shown but can't be picked."""
    options = []
    for m in candidates:
        available = is_available(state, m)
        price = f"${m.input:g}/${m.output:g}"
        flag = " (no access)" if available is False else " (not checked)" if available is None else ""
        options.append((m.key, f"{m.name:18} {m.id:18} {price:9} {m.note}{flag}", available is not False))
    return options


def choose_queen(default: str | None = None) -> Model:
    from hive import ui

    state = memory.load_state()
    return get(ui.choose("👑 Choose your Queen:", _menu(queens(), state), default or state.get("last_queen") or DEFAULT_QUEEN))


def choose_workers(default: str | None = None) -> Model:
    """Any model can be a bee; Haiku is the cheap default the hive is tuned for."""
    from hive import ui

    state = memory.load_state()
    return get(ui.choose("🐝 Choose the bee model:", _menu(list(CATALOG), state),
                         default or state.get("workers") or DEFAULT_WORKERS))


def mark_unavailable(model: Model, error: str) -> None:
    state = memory.load_state()
    access(state)[model.key] = {"ok": False, "error": error[:200], "checked_at": int(time.time())}
    memory.save_state(state)
