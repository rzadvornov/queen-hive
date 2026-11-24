"""Model catalog: who can be Queen, what each model costs, custom models, and access checks.

Claude, GPT and Gemini models each run in their own provider's CLI (Claude Code, Codex, Gemini CLI),
so a Queen and her bees always come from one provider. Custom models (OpenRouter, DeepSeek, Ollama, LM Studio …,
added with `hive models add`) can be bees in any of them, and a Queen in Claude Code.
"""

import asyncio
import dataclasses
import json
import os
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
    base_url: str | None = None       # custom models: where they're served (their first API's root)
    provider: str = "claude"          # claude | gpt | gemini: the CLI that runs it
    priced_on: str = PRICES_AS_OF     # when its price was last checked
    review: str = "full"              # its default review level as Queen
    anthropic_url: str | None = None  # custom models: root of an Anthropic Messages API (<root>/v1/messages)
    openai_url: str | None = None     # custom models: root of an OpenAI API (<root>/v1/chat/completions, /v1/responses)
    key_env: str | None = None        # custom models: the environment variable holding the API key

    @property
    def local(self) -> bool:
        """A custom model (the name is from when they all ran on this machine): served by its own endpoint."""
        return self.base_url is not None

    custom = local

    def api_key(self) -> str | None:
        return os.environ.get(self.key_env) if self.key_env else None

    def cache_write(self, ttl: str = "1h") -> float:
        """Cache writes cost 2x input for the 1-hour TTL (main sessions), 1.25x for 5 minutes (subagents)."""
        return self.input * (2.0 if ttl == "1h" else 1.25)


CATALOG: tuple[Model, ...] = (
    Model("fable-5.1", "claude-fable-5-1", "Claude Fable 5.1", 10.0, 50.0, 0.25, "xhigh", "most capable"),
    Model("mythos-5.1", "claude-mythos-5-1", "Claude Mythos 5.1", 10.0, 50.0, 1.0, "xhigh", "Project Glasswing only"),
    Model("opus-5.5", "claude-opus-5-5", "Claude Opus 5.5", 4.0, 20.0, 0.20, "xhigh", "default Queen"),
    Model("sonnet-5.5", "claude-sonnet-5-5", "Claude Sonnet 5.5", 2.0, 10.0, 0.20, "high", "fast and cheap",
          review="light"),   # the benchmarks: a full review cost a Sonnet hive more than Sonnet alone for no change
    Model("opus-5", "claude-opus-5", "Claude Opus 5", 5.0, 25.0, 0.50, "xhigh"),
    Model("opus-4.8", "claude-opus-4-8", "Claude Opus 4.8", 5.0, 25.0, 0.50, "xhigh"),
    Model("haiku-5.5", "claude-haiku-5-5", "Claude Haiku 5.5", 0.10, 0.50, 0.01, None, "worker bees"),
    Model("gpt-5.5", "gpt-5.5", "GPT-5.5", 5.0, 30.0, 0.50, "high", "default GPT Queen", provider="gpt"),
    Model("gpt-5.4", "gpt-5.4", "GPT-5.4", 2.50, 15.0, 0.25, "high", provider="gpt"),
    Model("gpt-5.3-codex", "gpt-5.3-codex", "GPT-5.3 Codex", 1.75, 14.0, 0.175, "high", "coding", provider="gpt"),
    Model("gpt-6-luna", "gpt-6-luna", "GPT-6 Luna", 0.10, 0.50, 0.01, None, "worker bees", provider="gpt",
          priced_on="2026-11-22"),
    Model("gpt-5.4-mini", "gpt-5.4-mini", "GPT-5.4 mini", 0.25, 2.0, 0.025, None, "older bees", provider="gpt"),
    Model("gemini-3.1-pro", "gemini-3.1-pro-preview", "Gemini 3.1 Pro", 2.0, 12.0, 0.20, "high", "default Gemini Queen",
          provider="gemini"),
    Model("gemini-3.8-flash", "gemini-3.8-flash", "Gemini 3.8 Flash", 0.75, 3.75, 0.075, "high", "fast",
          provider="gemini"),
    Model("gemini-3-flash", "gemini-3-flash-preview", "Gemini 3 Flash", 0.50, 3.0, 0.05, None, "worker bees",
          provider="gemini"),
    Model("gemini-3.5-flash-lite", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", 0.30, 2.50, 0.03, None,
          "worker bees", provider="gemini", priced_on="2026-11-22"),
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
CUSTOM_QUEEN = "custom"   # queen_effort of a custom model allowed as Queen: no effort setting is sent
# Where `hive models add --via NAME` finds a model: (Anthropic API root, OpenAI API root, API key variable)
PRESETS: dict[str, tuple[str | None, str | None, str | None]] = {
    "ollama": (OLLAMA_URL, OLLAMA_URL, None),
    "lmstudio": ("http://localhost:1234", "http://localhost:1234", None),
    "llamacpp": (None, "http://localhost:8080", None),
    "vllm": (None, "http://localhost:8000", None),
    "openrouter": ("https://openrouter.ai/api", "https://openrouter.ai/api", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com/anthropic", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "groq": (None, "https://api.groq.com/openai", "GROQ_API_KEY"),
    "together": (None, "https://api.together.xyz", "TOGETHER_API_KEY"),
}


def local_path():
    return memory.hive_home() / "models.json"


def _entries() -> list[dict]:
    """The custom models in ~/.hive/models.json ("local" is where they were kept before)."""
    settings = _settings()
    entries = [*(settings.get("custom") or []), *(settings.get("local") or [])]
    return [e for e in entries if isinstance(e, dict) and e.get("key") and e.get("id")]


def _custom(entry: dict) -> Model:
    old = entry.get("base_url")   # an entry from before: one server with both APIs, like Ollama
    anthropic_url = entry.get("anthropic_url") or (old if old else None)
    openai_url = entry.get("openai_url") or (old if old else None)
    if not (anthropic_url or openai_url):
        anthropic_url = openai_url = OLLAMA_URL
    price = entry.get("price") if isinstance(entry.get("price"), dict) else {}
    number = lambda k: float(price[k]) if isinstance(price.get(k), (int, float)) else 0.0
    return Model(entry["key"], entry["id"], entry.get("name") or entry["id"], number("input"), number("output"),
                 number("cache_read"), CUSTOM_QUEEN if entry.get("queen") else None, entry.get("note") or "custom",
                 (anthropic_url or openai_url).rstrip("/"), anthropic_url=anthropic_url and anthropic_url.rstrip("/"),
                 openai_url=openai_url and openai_url.rstrip("/"), key_env=entry.get("key_env") or None)


def local_models() -> list[Model]:
    """Custom models from ~/.hive/models.json: local servers (Ollama, LM Studio, llama.cpp, vLLM …) and hosted APIs
    (OpenRouter, DeepSeek, Groq …). Free unless you give them a price."""
    seen, models = set(), []
    for entry in _entries():
        if entry["key"] not in seen:
            seen.add(entry["key"])
            models.append(_custom(entry))
    return models


custom_models = local_models


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
    settings = {k: v for k, v in _settings().items() if k != "local"}
    path.write_text(json.dumps({**settings, "custom": entries}, indent=2, ensure_ascii=False) + "\n")


def _entry(model: Model) -> dict:
    entry = {"key": model.key, "id": model.id, "name": model.name, "anthropic_url": model.anthropic_url,
             "openai_url": model.openai_url, "key_env": model.key_env, "queen": bool(model.queen_effort)}
    if model.input or model.output or model.cache_read:
        entry["price"] = {"input": model.input, "output": model.output, "cache_read": model.cache_read}
    return {k: v for k, v in entry.items() if v not in (None, False)}


def add_local(key: str, model_id: str, base_url: str | None = None, name: str | None = None, *, via: str | None = None,
              anthropic_url: str | None = None, openai_url: str | None = None, key_env: str | None = None,
              queen: bool = False, price: tuple[float, float, float] | None = None) -> Model:
    """Add (or replace) a custom model. --via picks a preset's URLs and key variable; explicit ones win.
    base_url: one server with both APIs, as before."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key):
        raise SystemExit(f"'{key}': use letters, digits, '.', '_' and '-' only (it becomes part of a folder name).")
    if any(m.key == key for m in CATALOG):
        raise SystemExit(f"'{key}' is a catalog model's key; pick another name.")
    if via and via not in PRESETS:
        raise SystemExit(f"--via {via}: unknown. Known: {', '.join(PRESETS)}")
    if via:
        preset_anthropic, preset_openai, preset_key = PRESETS[via]
    elif anthropic_url or openai_url or base_url:
        preset_anthropic = preset_openai = preset_key = None
    else:   # nothing said: Ollama on this machine
        preset_anthropic, preset_openai, preset_key = PRESETS["ollama"]
    if base_url:
        preset_anthropic = preset_openai = base_url
    anthropic_url, openai_url = anthropic_url or preset_anthropic, openai_url or preset_openai
    entry = {"key": key, "id": model_id, "name": name or model_id, "anthropic_url": anthropic_url,
             "openai_url": openai_url, "key_env": key_env or preset_key, "queen": queen}
    if price:
        entry["price"] = dict(zip(("input", "output", "cache_read"), price))
    entries = [_entry(m) for m in local_models() if m.key != key]
    save_local([*entries, {k: v for k, v in entry.items() if v not in (None, False)}])
    return get(key)


def remove_local(key: str) -> bool:
    """Forget a custom model; False if there was none with that key."""
    current = local_models()
    kept = [m for m in current if m.key != key]
    save_local([_entry(m) for m in kept])
    return len(kept) < len(current)


def missing_keys(chosen: list[Model]) -> list[str]:
    """The API key variables these custom models need that aren't set."""
    return sorted({m.key_env for m in chosen if m.local and m.key_env and not os.environ.get(m.key_env)})


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
    return model if model and (model.provider == provider or model.local) else None


EFFORTS = ("low", "medium", "high", "xhigh", "max")
QUEEN_EFFORT_CAP = "high"   # coordinating needs less thinking than solving alone; thinking is billed as output


def coordinating_effort(model: Model) -> str | None:
    """The Queen's effort: her model's own, at most QUEEN_EFFORT_CAP. A model alone keeps its full effort.
    None for a custom Queen: her endpoint decides."""
    if not model.queen_effort or model.queen_effort not in EFFORTS:
        return None
    return EFFORTS[min(EFFORTS.index(model.queen_effort), EFFORTS.index(QUEEN_EFFORT_CAP))]


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


def prices_as_of(chosen: list[Model]) -> str:
    """The date of the prices of these models: one date, or the oldest to the newest."""
    dates = sorted({m.priced_on for m in chosen if not m.local and m.input}) or [PRICES_AS_OF]
    return dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"


def prices_note(provider: str) -> str:
    note = f"prices as of {prices_as_of(catalog(provider))}"
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


MIN_CONTEXT = 32_000   # Claude Code's own instructions are ~20k tokens; Ollama cuts longer prompts without saying


async def _probe_local(model: Model) -> tuple[bool, str]:
    """A tiny request through the API the model has (Anthropic first), with its key. True with a note when it works
    but Ollama gives it a context window too small for an agent."""
    import httpx

    if model.key_env and not model.api_key():
        return False, f"${model.key_env} isn't set"
    key = model.api_key() or "local"
    prompt = [{"role": "user", "content": "Reply with the single word OK."}]
    if model.anthropic_url:
        url, request = f"{model.anthropic_url}/v1/messages", {"model": model.id, "max_tokens": 8, "messages": prompt}
    else:
        url, request = f"{model.openai_url}/v1/chat/completions", {"model": model.id, "max_tokens": 8, "messages": prompt}
    try:
        async with httpx.AsyncClient(timeout=300) as client:   # the first request may load the model into memory
            response = await client.post(url, json=request, headers={
                "x-api-key": key, "authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"})
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}: {response.text[:150]}"
            return True, await _ollama_context_note(client, model)
    except httpx.HTTPError as error:
        return False, f"{url.split('/v1/')[0]} not reachable ({type(error).__name__}); is the server running?"


async def _ollama_context_note(client, model: Model) -> str:
    """Ollama lists loaded models with their context window; other servers don't have /api/ps."""
    try:
        response = await client.get(f"{model.base_url}/api/ps", timeout=5)
        loaded = {m.get("name"): m.get("context_length") for m in response.json().get("models", [])}
    except Exception:   # not Ollama, or an older one
        return ""
    size = loaded.get(model.id)
    if isinstance(size, int) and size < MIN_CONTEXT:
        return f"context window {size:,} tokens: too small, start Ollama with OLLAMA_CONTEXT_LENGTH=65536"
    return ""


SIGN_IN_ERRORS = re.compile(r"authenticat|IneligibleTier|api.?key|not logged in|log ?in|unauthori[sz]ed|credential|\b401\b",
                            re.I)


async def check_access(keys: list[str] | None = None, provider: str = "claude") -> dict[str, dict]:
    """Probe models concurrently and cache the result in ~/.hive/state.json."""
    bees = DEFAULTS[provider][1]
    chosen = [get(k) for k in keys] if keys else [m for m in catalog(provider) if m.queen_effort or m.key == bees] + (
        local_models())
    results = await asyncio.gather(*(probe(m) for m in chosen))
    state = memory.load_state()
    now = int(time.time())
    for model, (ok, error) in zip(chosen, results):
        if not ok and SIGN_IN_ERRORS.search(error) and model.key in access(state):
            continue   # about your login, not the model: keep what the last real check found
        access(state)[model.key] = {"ok": ok, "error": error, "checked_at": now}
    memory.save_state(state)
    return {model.key: {"ok": ok, "error": error} for model, (ok, error) in zip(chosen, results)}


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
