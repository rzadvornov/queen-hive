"""Model catalog: who can be Queen, what each model costs, local models, and access checks.

Claude, GPT and Gemini models each run in their own provider's CLI (Claude Code, Codex, Gemini CLI),
so a Queen and her bees always come from one provider.
"""

import asyncio
import dataclasses
import json
import re
import time
from dataclasses import dataclass

from hive import memory

PRICES_AS_OF = "2026-10-06"
ESTIMATED_PRICES = {"gpt", "gemini"}   # from price trackers, not the providers' own pages: override in ~/.hive/models.json


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
    provider: str = "claude"          # claude | gpt | gemini: the CLI that runs it

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
    Model("gpt-5.5", "gpt-5.5", "GPT-5.5", 5.0, 30.0, 0.50, "high", "default GPT Queen", provider="gpt"),
    Model("gpt-5.4", "gpt-5.4", "GPT-5.4", 2.50, 15.0, 0.25, "high", provider="gpt"),
    Model("gpt-5.3-codex", "gpt-5.3-codex", "GPT-5.3 Codex", 1.75, 14.0, 0.175, "high", "coding", provider="gpt"),
    Model("gpt-6-luna", "gpt-6-luna", "GPT-6 Luna", 0.10, 0.50, 0.01, None, "worker bees", provider="gpt"),
    Model("gpt-5.4-mini", "gpt-5.4-mini", "GPT-5.4 mini", 0.25, 2.0, 0.025, None, "older bees", provider="gpt"),
    Model("gemini-3.1-pro", "gemini-3.1-pro-preview", "Gemini 3.1 Pro", 2.0, 12.0, 0.20, "high", "default Gemini Queen",
          provider="gemini"),
    Model("gemini-3.8-flash", "gemini-3.8-flash", "Gemini 3.8 Flash", 0.75, 3.75, 0.075, "high", "fast",
          provider="gemini"),
    Model("gemini-3-flash", "gemini-3-flash-preview", "Gemini 3 Flash", 0.50, 3.0, 0.05, None, "worker bees",
          provider="gemini"),
    Model("gemini-3.5-flash-lite", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", 0.30, 2.50, 0.03, None,
          "worker bees", provider="gemini"),
    Model("gemini-3.1-flash-lite", "gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", 0.25, 1.50, 0.025, None,
          "cheapest bees", provider="gemini"),
)

DEFAULT_QUEEN = "opus-5.5"
DEFAULT_WORKERS = "haiku-5.5"
DEFAULT_COMPARE = ("sonnet-5.5", "opus-4.8", "opus-5.5")
DEFAULTS = {   # provider → (Queen, bees)
    "claude": (DEFAULT_QUEEN, DEFAULT_WORKERS),
    "gpt": ("gpt-5.5", "gpt-6-luna"),
    "gemini": ("gemini-3.1-pro", "gemini-3.5-flash-lite"),
}
OLLAMA_URL = "http://localhost:11434"


def local_path():
    return memory.hive_home() / "models.json"


def local_models() -> list[Model]:
    """Models served on this machine (Ollama, llama.cpp, LM Studio …), from ~/.hive/models.json. They cost nothing."""
    entries = _settings().get("local") or []
    return [Model(e["key"], e["id"], e.get("name") or e["id"], 0.0, 0.0, 0.0, None, "local", e.get("base_url") or OLLAMA_URL)
            for e in entries if isinstance(e, dict) and e.get("key") and e.get("id")] if isinstance(entries, list) else []


def _settings() -> dict:
    try:
        data = json.loads(local_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def price_overrides() -> dict[str, dict]:
    """Your own prices from ~/.hive/models.json: {"prices": {"gpt-5.5": {"input": 5, "output": 30, "cache_read": 0.5}}}."""
    prices = _settings().get("prices")
    return prices if isinstance(prices, dict) else {}


def save_local(entries: list[dict]) -> None:
    path = local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**_settings(), "local": entries}, indent=2, ensure_ascii=False) + "\n")


def add_local(key: str, model_id: str, base_url: str = OLLAMA_URL, name: str | None = None) -> Model:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key):
        raise SystemExit(f"'{key}': use letters, digits, '.', '_' and '-' only (it becomes part of a folder name).")
    if any(m.key == key for m in CATALOG):
        raise SystemExit(f"'{key}' is a catalog model's key; pick another name.")
    entries = [{"key": m.key, "id": m.id, "name": m.name, "base_url": m.base_url} for m in local_models() if m.key != key]
    save_local([*entries, {"key": key, "id": model_id, "name": name or model_id, "base_url": base_url.rstrip("/")}])
    return get(key)


def remove_local(key: str) -> bool:
    """Forget a local model; False if there was none with that key."""
    current = local_models()
    kept = [m for m in current if m.key != key]
    save_local([{"key": m.key, "id": m.id, "name": m.name, "base_url": m.base_url} for m in kept])
    return len(kept) < len(current)


def catalog(provider: str | None = None) -> list[Model]:
    """Every known model, or one provider's. Local models run as bees in Claude Code sessions."""
    overrides = price_overrides()
    models = [_priced(m, overrides.get(m.key)) for m in [*CATALOG, *_codex_offered()]] + local_models()
    return [m for m in models if provider is None or m.provider == provider]


def _codex_offered() -> list[Model]:
    """Models your Codex account offers that the catalog doesn't know. Their price is unknown
    (a ChatGPT plan isn't billed per token), so costs show as $0 unless you set one."""
    from hive import codex

    known = {m.id for m in CATALOG}
    return [Model(slug, slug, name, 0.0, 0.0, 0.0, "high", description or "from your Codex account", provider="gpt")
            for slug, name, description in codex.offered() if slug not in known]


def _priced(model: Model, override) -> Model:
    if not isinstance(override, dict):
        return model
    fields = {k: float(override[k]) for k in ("input", "output", "cache_read") if isinstance(override.get(k), (int, float))}
    return dataclasses.replace(model, **fields) if fields else model


def defaults(provider: str) -> tuple[Model, Model]:
    queen, workers = DEFAULTS[provider]
    if provider == "gpt":   # a ChatGPT plan may not offer the API's models: use Codex's own default
        from hive import codex

        slugs = [slug for slug, _, _ in codex.offered()]
        if slugs:
            usable = [get(slug) for slug in slugs]
            queens_offered = [m for m in usable if m.queen_effort]
            return (get(queen) if queen in slugs else (queens_offered or usable)[0],
                    get(workers) if workers in slugs else usable[0])
    return get(queen), get(workers)


def remembered(state: dict, provider: str) -> tuple[Model, Model]:
    """The Queen and bee models last used with this provider, else its defaults."""
    saved = state.get("by_provider", {}).get(provider, {})
    if provider == "claude":   # where these were kept before there were providers
        saved = {"queen": state.get("last_queen"), "workers": state.get("workers"), **{k: v for k, v in saved.items() if v}}
    queen, workers = defaults(provider)
    return (_of(saved.get("queen"), provider) or queen, _of(saved.get("workers"), provider) or workers)


def remember(state: dict, queen: Model, workers: Model) -> None:
    state.setdefault("by_provider", {})[queen.provider] = {"queen": queen.key, "workers": workers.key}
    if queen.provider == "claude":
        state.update(last_queen=queen.key, workers=workers.key)


def _of(key: str | None, provider: str) -> Model | None:
    model = find(key) if key else None
    return model if model and (model.provider == provider or (provider == "claude" and model.local)) else None


def default_compare(provider: str) -> list[str]:
    """The single models a job's cost is compared with."""
    if provider == "claude":
        return list(DEFAULT_COMPARE)
    offered = _account_models(provider)
    return [m.key for m in queens(provider) if m.input and (offered is None or m.id in offered)]


def _account_models(provider: str) -> set[str] | None:
    """The model ids your account can use, when the CLI says (Codex does); None if unknown."""
    if provider != "gpt":
        return None
    from hive import codex

    return {slug for slug, _, _ in codex.offered()} or None


def prices_note(provider: str) -> str:
    note = f"prices as of {PRICES_AS_OF}"
    return note + " (estimates from price trackers; set your own in ~/.hive/models.json)" if provider in ESTIMATED_PRICES else note


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


def queens(provider: str | None = "claude") -> list[Model]:
    return [m for m in catalog(provider) if m.queen_effort]


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
    if model.provider != "claude":
        from hive import providers

        return await asyncio.to_thread(providers.runtime(model.provider).probe, model)
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


async def check_access(keys: list[str] | None = None, provider: str = "claude") -> dict[str, dict]:
    """Probe models concurrently and cache the result in ~/.hive/state.json."""
    bees = DEFAULTS[provider][1]
    chosen = [get(k) for k in keys] if keys else [m for m in catalog(provider) if m.queen_effort or m.key == bees] + (
        local_models() if provider == "claude" else [])
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


def choose_queen(default: str | None = None, provider: str = "claude") -> Model:
    from hive import ui

    state = memory.load_state()
    return get(ui.choose("👑 Choose your Queen:", _menu(queens(provider), state),
                         default or remembered(state, provider)[0].key))


def choose_workers(default: str | None = None, provider: str = "claude") -> Model:
    """Any of the provider's models can be a bee; the cheapest are the defaults the hive is tuned for."""
    from hive import ui

    state = memory.load_state()
    return get(ui.choose("🐝 Choose the bee model:", _menu(catalog(provider), state),
                         default or remembered(state, provider)[1].key))


def mark_unavailable(model: Model, error: str) -> None:
    state = memory.load_state()
    access(state)[model.key] = {"ok": False, "error": error[:200], "checked_at": int(time.time())}
    memory.save_state(state)
