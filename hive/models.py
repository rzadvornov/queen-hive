"""Model catalog: who can be Queen, what each model costs, local models, and access checks."""

import asyncio
import json
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
    base_url: str | None = None       # local models: their own Anthropic-compatible server, e.g. Ollama

    @property
    def local(self) -> bool:
        return self.base_url is not None

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
OLLAMA_URL = "http://localhost:11434"


def local_path():
    return memory.hive_home() / "models.json"


def local_models() -> list[Model]:
    """Models served on this machine (Ollama, llama.cpp, LM Studio …), from ~/.hive/models.json. They cost nothing."""
    try:
        entries = json.loads(local_path().read_text()).get("local", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [Model(e["key"], e["id"], e.get("name") or e["id"], 0.0, 0.0, 0.0, None, "local", e.get("base_url") or OLLAMA_URL)
            for e in entries if isinstance(e, dict) and e.get("key") and e.get("id")]


def save_local(entries: list[dict]) -> None:
    path = local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"local": entries}, indent=2, ensure_ascii=False) + "\n")


def add_local(key: str, model_id: str, base_url: str = OLLAMA_URL, name: str | None = None) -> Model:
    if any(m.key == key for m in CATALOG):
        raise SystemExit(f"'{key}' is a Claude model's key; pick another name.")
    entries = [{"key": m.key, "id": m.id, "name": m.name, "base_url": m.base_url} for m in local_models() if m.key != key]
    save_local([*entries, {"key": key, "id": model_id, "name": name or model_id, "base_url": base_url.rstrip("/")}])
    return get(key)


def remove_local(key: str) -> bool:
    """Forget a local model; False if there was none with that key."""
    current = local_models()
    kept = [m for m in current if m.key != key]
    save_local([{"key": m.key, "id": m.id, "name": m.name, "base_url": m.base_url} for m in kept])
    return len(kept) < len(current)


def catalog() -> list[Model]:
    return [*CATALOG, *local_models()]


def get(name: str) -> Model:
    """Look up a model by short key, API ID, or an ID with a suffix like '[1m]' or a date."""
    name = name.strip().lower()
    known = catalog()
    for model in known:
        if name in (model.key.lower(), model.id.lower()):
            return model
    for model in sorted(known, key=lambda m: -len(m.id)):
        if name.startswith(model.id.lower()):
            return model
    raise KeyError(f"unknown model '{name}'. Known: {', '.join(m.key for m in known)}")


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
    """Send a tiny request to see whether the current login (or, for a local model, its server) can serve this model."""
    if model.local:
        return await _probe_local(model)
    from hive import claude

    args = ["--model", model.id, "--tools", "", "--setting-sources", "", "--max-budget-usd", "0.05"]
    result = await asyncio.to_thread(claude.print_mode, args, "Reply with the single word OK.", None, None, 120)
    if result.get("is_error"):
        return False, str(result.get("result") or result.get("subtype") or "error").splitlines()[0][:200]
    served = list(result.get("modelUsage") or {})
    if served and not any(s.startswith(model.id) for s in served):
        return False, f"served by {', '.join(served)} instead"
    return True, ""


async def _probe_local(model: Model) -> tuple[bool, str]:
    import httpx

    request = {"model": model.id, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with the single word OK."}]}
    try:
        async with httpx.AsyncClient(timeout=300) as client:   # the first request loads the model into memory
            response = await client.post(f"{model.base_url}/v1/messages", json=request,
                                         headers={"x-api-key": "local", "anthropic-version": "2023-06-01"})
    except httpx.HTTPError as error:
        return False, f"{model.base_url} not reachable ({type(error).__name__}); is the server running?"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:150]}"
    return True, ""


async def check_access(keys: list[str] | None = None) -> dict[str, dict]:
    """Probe models concurrently and cache the result in ~/.hive/state.json."""
    chosen = [get(k) for k in keys] if keys else [m for m in catalog() if m.queen_effort or m.key == DEFAULT_WORKERS or m.local]
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
    return get(ui.choose("🐝 Choose the bee model:", _menu(catalog(), state),
                         default or state.get("workers") or DEFAULT_WORKERS))


def mark_unavailable(model: Model, error: str) -> None:
    state = memory.load_state()
    access(state)[model.key] = {"ok": False, "error": error[:200], "checked_at": int(time.time())}
    memory.save_state(state)
