"""Run records: what a job used, how it compares with single models, and history across runs."""

import datetime as dt
import json
import time
from pathlib import Path

from hive import memory, models, pricing
from hive.pricing import Tokens
from hive.render import Tracker


def weekly(rate_limits: list[dict]) -> dict:
    """Weekly-limit usage from rate-limit snapshots. The SDK reports them only on status changes."""
    week = [r for r in rate_limits if r.get("type") in ("seven_day", "seven_day_opus") and r.get("utilization") is not None]
    if not week:
        return {"reported": False}
    first, last = week[0]["utilization"], week[-1]["utilization"]
    return {"reported": True, "type": week[-1]["type"], "now": last,
            "delta": (last - first) if len(week) > 1 else None, "resets_at": week[-1].get("resets_at")}


def _ratio(exact: Tokens, seen: Tokens) -> Tokens:
    def r(a: int, b: int) -> float:
        return a / b if b else 1.0

    return Tokens(r(exact.input, seen.input), r(exact.output, seen.output),
                  r(exact.cache_read, seen.cache_read), r(exact.cache_write, seen.cache_write))


def stage_usage(tracker: Tracker, exact_by_model: dict[str, Tokens]) -> dict[str, dict]:
    """Tokens and cost per stage.

    Streamed messages undercount some fields (output especially), so each stage's share
    of a model is scaled to the CLI's exact per-model totals.
    """
    seen = tracker.tokens_by_model()
    stages: dict[str, dict] = {}
    for (stage, model), tokens in tracker.usage.items():
        exact = exact_by_model.get(model)
        if exact and model in seen:
            tokens = tokens.scaled(_ratio(exact, seen[model]))
        entry = stages.setdefault(stage, {"tokens": Tokens(), "cost_usd_est": 0.0})
        entry["tokens"].add(tokens)
        entry["cost_usd_est"] += pricing.cost_by_id(tokens, model, "1h" if stage == "queen" else "5m") or 0.0
    return {stage: {"tokens": e["tokens"].to_dict(), "cost_usd_est": e["cost_usd_est"]} for stage, e in stages.items()}


def hive_section(tracker: Tracker) -> dict:
    result = tracker.result   # session totals are cumulative, so the last turn's result has everything
    by_model = tracker.tokens_by_model()
    if result and result.model_usage:  # the CLI's own per-model totals are authoritative
        by_model = {model: Tokens.from_usage(usage) for model, usage in result.model_usage.items()}
    total = Tokens()
    for tokens in by_model.values():
        total.add(tokens)
    return {
        "cost_usd": result.total_cost_usd if result else None,
        "duration_ms": int((time.time() - tracker.started) * 1000),
        "api_ms": result.duration_api_ms if result else None,
        "turns": len(tracker.results),
        "is_error": result.is_error if result else True,
        "subtype": result.subtype if result else "no_result",
        "tokens": total.to_dict(),
        "by_model": {
            model: {"tokens": t.to_dict(), "cost_usd": (result.model_usage or {}).get(model, {}).get("costUSD")
                    if result and result.model_usage else pricing.cost_by_id(t, model)}
            for model, t in by_model.items()
        },
        "by_stage": stage_usage(tracker, by_model),
        "briefs": [{"label": d.label, "agent": d.agent, "stage": d.stage, "description": d.description, "status": d.status}
                   for d in tracker.dispatches.values()],
        "returns": tracker.returns,
        "checks": tracker.checks,
    }


def estimates(total: dict, keys: list[str]) -> list[dict]:
    tokens = Tokens(**total)
    return [{"model": k, "name": models.get(k).name, "cost_usd": pricing.cost(tokens, models.get(k))} for k in keys]


def baseline(record: dict) -> tuple[str, float, bool] | None:
    """What the Queen model alone would have cost: a real compare run if there is one, else the estimate."""
    queen = record["queen"]["key"]
    for entry in record.get("compare", []):
        if entry["model"] == queen and entry.get("cost_usd") is not None:
            return entry["name"], entry["cost_usd"], True
    for entry in record.get("estimates", []):
        if entry["model"] == queen:
            return entry["name"], entry["cost_usd"], False
    return None


# --- terminal ---------------------------------------------------------------

def _k(n: int | None) -> str:
    if n is None:
        return "–"
    return f"{n / 1_000_000:.2f}M" if n >= 1_000_000 else f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _usd(x: float | None) -> str:
    return "–" if x is None else f"${x:.2f}" if x >= 0.995 else f"${x:.3f}"


def _secs(ms: int | None) -> str:
    if ms is None:
        return "–"
    s = ms / 1000
    return f"{s:.0f}s" if s < 120 else f"{s / 60:.1f}m"


def _ok(value: bool | None) -> str:
    return "–" if value is None else "✅" if value else "❌"


def print_report(record: dict) -> None:
    hive = record["hive"]
    week = record.get("weekly", {})
    week_txt = "not reported"
    if week.get("reported"):
        week_txt = f"{week['now']:.0%} used" + (f" (+{week['delta']:.1%} this job)" if week.get("delta") is not None else "")

    rows = [("variant", "passed", "tokens in/out", "cache r/w", "cost", "time")]
    t = hive["tokens"]
    rows.append((f"🐝 Hive ({record['queen']['name']} + {record['workers']['name']})", _ok(record["acceptance"]["passed"]),
                 f"{_k(t['input'])}/{_k(t['output'])}", f"{_k(t['cache_read'])}/{_k(t['cache_write'])}",
                 _usd(hive["cost_usd"]), _secs(hive["duration_ms"])))
    for stage, data in sorted(hive["by_stage"].items(), key=lambda kv: list("qsbrf").index(kv[0][0]) if kv[0][0] in "qsbrf" else 9):
        st = data["tokens"]
        rows.append((f"   └ {stage}", "", f"{_k(st['input'])}/{_k(st['output'])}", f"{_k(st['cache_read'])}/{_k(st['cache_write'])}",
                     "≈" + _usd(data["cost_usd_est"]), ""))
    for entry in record.get("compare", []):
        ct = entry.get("tokens") or {}
        rows.append((f"⚖️  {entry['name']} alone", _ok(entry.get("passed")),
                     f"{_k(ct.get('input'))}/{_k(ct.get('output'))}", f"{_k(ct.get('cache_read'))}/{_k(ct.get('cache_write'))}",
                     _usd(entry.get("cost_usd")), _secs(entry.get("duration_ms"))))
    for entry in record.get("estimates", []):
        rows.append((f"≈  {entry['name']} alone (estimate)", "", "", "", _usd(entry["cost_usd"]), ""))

    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    line = "─" * (sum(widths) + 3 * (len(widths) - 1))
    print("\n" + line)
    for i, row in enumerate(rows):
        print("   ".join(str(cell).ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print(line)
    print(line)

    acc = record["acceptance"]
    if acc["commands"]:
        for res in acc["results"]:
            print(f"acceptance {_ok(res['ok'])} $ {res['command']}")
    else:
        print("acceptance – no acceptance command (use --done \"CMD\" or set `test:` in the profile)")
    print(f"weekly limit: {week_txt}")
    review = (record.get("summary") or {}).get("review") or {}
    if review:
        print(f"review: lenses {', '.join(review.get('lenses', [])) or '–'} · confirmed {review.get('confirmed', 0)} · "
              f"fixed {review.get('fixed', 0)} · dismissed {review.get('dismissed', 0)} · open {len(review.get('open', []))}")
    base = baseline(record)
    if base and hive["cost_usd"]:
        name, cost, real = base
        saved = 1 - hive["cost_usd"] / cost if cost else 0
        verb = "saved" if saved >= 0 else "cost more by"
        kind = "measured" if real else "estimate, same tokens"
        print(f"🐝 Hive {_usd(hive['cost_usd'])} vs {name} alone {_usd(cost)} ({kind}) → {verb} {abs(saved):.0%}")
    if not record.get("compare"):
        print("   estimates assume the same token count; run with --compare for a real side-by-side.")
    print(f"run saved: {record['path']}")


# --- history ----------------------------------------------------------------

def save(record: dict, run_dir: Path) -> Path:
    path = run_dir / "run.json"
    record["path"] = str(path)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    return path


def load_runs(pdirs: list[Path]) -> list[dict]:
    runs = []
    for pdir in pdirs:
        for path in sorted((pdir / "runs").glob("*/run.json")):
            try:
                runs.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
    return sorted(runs, key=lambda r: r.get("started_at", 0))


def print_history(folder: Path | None) -> None:
    pdirs = [memory.project_dir(folder)] if folder else memory.all_projects()
    runs = load_runs(pdirs)
    if not runs:
        print("No hive runs yet.")
        return
    print(f"{'when':16} {'project':18} {'queen':16} {'mode':5} {'pass':4} {'cost':>8} {'saved':>7}  goal")
    total = 0.0
    savings = []
    for run in runs:
        when = dt.datetime.fromtimestamp(run["started_at"]).strftime("%Y-%m-%d %H:%M")
        cost = run["hive"].get("cost_usd") or 0
        total += cost
        base = baseline(run)
        saved = ""
        if base and base[1] and cost:
            savings.append(1 - cost / base[1])
            saved = f"{savings[-1]:.0%}"
        project = Path(run["folders"][0]).name[:18]
        print(f"{when:16} {project:18} {run['queen']['name'][7:23]:16} {run['mode']:5} {_ok(run['acceptance']['passed']):4} "
              f"{_usd(cost):>8} {saved:>7}  {run['goal'][:60]}")
    passed = [r["acceptance"]["passed"] for r in runs if r["acceptance"]["passed"] is not None]
    print(f"\n{len(runs)} runs · total {_usd(total)} · pass rate "
          f"{(sum(passed) / len(passed)):.0%}" if passed else f"\n{len(runs)} runs · total {_usd(total)}", end="")
    print(f" · average saving vs Queen alone {sum(savings) / len(savings):.0%}" if savings else "")
