"""The harder benchmark (design: HARDER.md): realistic issues, scored on tests no agent sees.

    python3 bench/run_hard.py                 # every task in bench/hard
    python3 bench/run_hard.py ledger report   # some of them
    python3 bench/run_hard.py --table         # only rebuild bench/HARD-RESULTS.md

Each task has an issue text, a repo with its visible tests, and two folders no agent sees: hidden/ (does the
change do what the issue needs) and regression/ (does what worked before still work). Variants:

- hive:        Opus 5.5 Queen, Haiku 5.5 bees, full review; `--compare` also runs Sonnet 5.5 and Opus 5.5
               alone in copies of the starting repo
- hive light:  Sonnet 5.5 Queen, Haiku 5.5 bees, light review

Every variant gets the same issue text, the visible test command as its check, and the same cap. Afterwards each
variant's change is put on a fresh copy of the starting repo with the hidden tests added, and scored there.
Runs use their own hive home (~/.hive-bench), apart from your own statistics.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
HOME = Path(os.environ.get("HIVE_BENCH_HOME", Path.home() / ".hive-bench")) / "hard"
BUDGET, LIMIT = "8", 3600   # USD per run; seconds for one hive run including its --compare runs
SOLO = "sonnet-5.5,opus-5.5"
VARIANTS = {"hive": ["--queen", "opus-5.5", "--review", "full", "--compare", SOLO, "--yes"],
            "hive light": ["--queen", "sonnet-5.5", "--review", "light"],
            "hive sonnet": ["--queen", "sonnet-5.5", "--compare", "sonnet-5.5", "--yes"]}   # its default review
DEFAULT_VARIANTS = ("hive", "hive light")   # --variants "hive sonnet" runs others

os.environ["HIVE_HOME"] = str(HOME / "home")
sys.path.insert(0, str(BENCH.parent))
from hive import memory  # noqa: E402  (after HIVE_HOME is set)

PROFILE = """# Project profile

## Stack
- Python 3, standard library only, unittest

## Commands
- test: {test}

## Protected paths
<!-- Paths the hive must never change, relative to the project root. A trailing / means a whole folder. -->

## Notes
"""


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@localhost", "-C", str(cwd), *args],
                          capture_output=True, text=True)


def fresh(task: str, where: Path) -> Path:
    """A git copy of the task's starting repo."""
    shutil.rmtree(where, ignore_errors=True)
    shutil.copytree(BENCH / "hard" / task / "repo", where)
    git(where, "init", "-q")
    git(where, "add", "-A")
    git(where, "commit", "-q", "-m", "start")
    return where


def score(task: str, workspace: Path) -> dict:
    """Hidden and regression tests on a workspace, copied in only now."""
    result = {}
    for kind in ("hidden", "regression"):
        target = workspace / f"{kind}_tests"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(BENCH / "hard" / task / kind, target)
        (target / "__init__.py").touch()
        try:
            done = subprocess.run([sys.executable, str(BENCH / "score_tests.py"), target.name], cwd=workspace,
                                  capture_output=True, text=True, timeout=600)
            result[kind] = json.loads(done.stdout.strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, ValueError, IndexError):
            result[kind] = {"run": 0, "passed": 0, "failed": ["the tests didn't finish"]}
    return result


def run_variant(task: str, info: dict, variant: str) -> list[dict]:
    """One hive run (and, for the full hive, its single-model comparisons); a scored entry per variant."""
    work = fresh(task, HOME / "work" / f"{task}-{variant.replace(' ', '-')}")
    pdir = memory.ensure_project(work)
    shutil.rmtree(pdir / "runs", ignore_errors=True)
    (pdir / "runs").mkdir()
    (pdir / "profile.md").write_text(PROFILE.format(test=info["test"]))
    log = HOME / "logs" / f"{task}-{variant.replace(' ', '-')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "hive.cli", info["issue"], "--headless", "-d", str(work), "--done", info["test"],
            "--provider", "claude", "--workers", "haiku-5.5", "--mode", "auto", "--budget", BUDGET, "--no-init",
            *VARIANTS[variant]]
    started = time.time()
    with log.open("w") as out:
        try:
            subprocess.run(argv, stdout=out, stderr=subprocess.STDOUT, cwd=BENCH.parent, env=os.environ, timeout=LIMIT)
        except subprocess.TimeoutExpired:
            out.write(f"\n[bench] stopped after {LIMIT}s\n")
    records = sorted((pdir / "runs").glob("*/run.json"))
    record = json.loads(records[-1].read_text()) if records else None
    entries = [{"task": task, "variant": variant, "cost_usd": record["hive"]["cost_usd"] if record else None,
                "duration_ms": record["hive"]["duration_ms"] if record else int((time.time() - started) * 1000),
                "error": None if record else f"no run recorded (log: {log})", **score(task, work)}]
    for solo in (record or {}).get("compare", []):
        copy = fresh(task, HOME / "work" / f"{task}-{solo['model']}")
        diff = Path(solo.get("diff") or "")
        applied = git(copy, "apply", "--whitespace=nowarn", str(diff)) if diff.is_file() and diff.stat().st_size else None
        entries.append({"task": task, "variant": f"{solo['name']} alone", "cost_usd": solo.get("cost_usd"),
                        "duration_ms": solo.get("duration_ms"),
                        "error": solo.get("error") or (applied.stderr.strip()[:200] if applied and applied.returncode else None),
                        **score(task, copy)})
    return entries


def table(results: list[dict]) -> str:
    def pct(part: dict) -> str:
        return f"{100 * part['passed'] / part['run']:.0f}%" if part.get("run") else "–"

    variants = list(dict.fromkeys(r["variant"] for r in results))
    tasks = list(dict.fromkeys(r["task"] for r in results))
    by = {(r["task"], r["variant"]): r for r in results}
    lines = ["Each cell: hidden tests passed · regressions · cost · time.", "",
             "| Task | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for task in tasks:
        cells = []
        for variant in variants:
            r = by.get((task, variant))
            if not r:
                cells.append("–")
                continue
            regressions = r["regression"]["run"] - r["regression"]["passed"]
            cost = f"${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else "–"
            mins = f"{r['duration_ms'] / 60000:.1f}m" if r.get("duration_ms") else "–"
            cells.append(f"{pct(r['hidden'])} · {regressions} · {cost} · {mins}" + (" ⚠️" if r.get("error") else ""))
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    summary = []
    for variant in variants:
        rows = [r for r in results if r["variant"] == variant]
        correct = sum(1 for r in rows if r["hidden"]["run"] and r["hidden"]["passed"] / r["hidden"]["run"] >= 0.95
                      and r["regression"]["passed"] == r["regression"]["run"])
        cost = sum(r.get("cost_usd") or 0 for r in rows)
        summary.append(f"**{correct}/{len(rows)} correct · ${cost:.2f}**"
                       + (f" · ${cost / correct:.2f} per correct task" if correct else ""))
    lines.append("| **Total** | " + " | ".join(summary) + " |")
    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]
    chosen = DEFAULT_VARIANTS
    if "--variants" in args:
        i = args.index("--variants")
        chosen = tuple(v.strip() for v in args[i + 1].split(","))
        args = args[:i] + args[i + 2:]
    names = [a for a in args if not a.startswith("--")]
    path = BENCH / "hard-results.json"
    results = json.loads(path.read_text()) if path.exists() else []
    if "--table" not in sys.argv:
        for task in names or sorted(p.name for p in (BENCH / "hard").iterdir() if p.is_dir()):
            info = json.loads((BENCH / "hard" / task / "task.json").read_text())
            for variant in chosen:
                print(f"▶ {task} · {variant} …", flush=True)
                entries = run_variant(task, info, variant)
                for e in entries:
                    print(f"  {e['variant']}: hidden {e['hidden']['passed']}/{e['hidden']['run']} · regressions "
                          f"{e['regression']['run'] - e['regression']['passed']} · ${e['cost_usd'] or 0:.2f}"
                          + (f" · ⚠️ {e['error']}" if e.get("error") else ""), flush=True)
                results = [r for r in results if (r["task"], r["variant"]) not in {(e["task"], e["variant"]) for e in entries}]
                results += entries
                path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    (BENCH / "HARD-RESULTS.md").write_text("# Harder benchmark: pilot results\n\n" + table(results) + "\n")
    print("\n" + table(results))


if __name__ == "__main__":
    main()
