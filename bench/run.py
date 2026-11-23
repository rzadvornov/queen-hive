"""Benchmark: each task done by the hive and by single models alone, on the same acceptance tests.

    python3 bench/run.py                  # every task in bench/tasks
    python3 bench/run.py dates reports    # some of them
    python3 bench/run.py --table          # only rebuild bench/RESULTS.md from bench/results.json

Each task is a small repo (tasks/<name>/repo) with its own unit tests and a product owner's acceptance
test in acceptance/, which the hive treats as a protected path. The hive (Opus 5.5 Queen, Haiku 5.5
bees, full review) runs the goal headless, and `--compare` redoes it with each model alone in a copy
of the starting repo. The hive itself checks every variant with the acceptance command.

Runs use their own hive home (~/.hive-bench), so they don't show up in your own statistics.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
HOME = Path(os.environ.get("HIVE_BENCH_HOME", Path.home() / ".hive-bench"))
QUEEN = os.environ.get("BENCH_QUEEN", "opus-5.5")            # e.g. BENCH_QUEEN=sonnet-5.5 BENCH_SOLO=sonnet-5.5
SOLO = os.environ.get("BENCH_SOLO", "sonnet-5.5,opus-5.5")
TAG = "" if QUEEN == "opus-5.5" else f"-{QUEEN}"               # other Queens get their own result files
WORKERS, BUDGET = "haiku-5.5", "3"

os.environ["HIVE_HOME"] = str(HOME / "home")
sys.path.insert(0, str(BENCH.parent))
from hive import memory  # noqa: E402  (after HIVE_HOME is set)

PROFILE = """# Project profile

## Stack
- Python 3, standard library only, unittest

## Commands
- test: python3 -m unittest discover -s tests -t .

## Protected paths
<!-- Paths the hive must never change, relative to the project root. A trailing / means a whole folder. -->
- acceptance/

## Notes
- The acceptance/ tests belong to the product owner: never edit them.
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@localhost", "-C", str(cwd), *args],
                   check=True, capture_output=True)


def prepare(name: str) -> Path:
    """A fresh git copy of the task's repo, with a profile that protects its acceptance tests."""
    work = HOME / "work" / name
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(BENCH / "tasks" / name / "repo", work)
    git(work, "init", "-q")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "start")
    pdir = memory.ensure_project(work)
    shutil.rmtree(pdir / "runs", ignore_errors=True)
    (pdir / "runs").mkdir()
    (pdir / "profile.md").write_text(PROFILE)
    return work


def run(name: str) -> dict:
    task = json.loads((BENCH / "tasks" / name / "task.json").read_text())
    work = prepare(name)
    log = HOME / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "hive.cli", task["goal"], "--headless", "-d", str(work), "--done", task["done"],
            "--compare", SOLO, "--yes", "--provider", "claude", "--queen", QUEEN, "--workers", WORKERS,
            "--mode", "auto", "--budget", BUDGET, "--no-init"]
    print(f"▶ {name}: {task['kind']} …", flush=True)
    with log.open("w") as out:
        subprocess.run(argv, stdout=out, stderr=subprocess.STDOUT, cwd=BENCH.parent, env=os.environ)
    records = sorted((memory.project_dir(work) / "runs").glob("*/run.json"))
    if not records:
        print(f"  {name}: no run recorded, see {log}")
        return {"task": name, "kind": task["kind"], "error": f"no run recorded (log: {log})"}
    record = json.loads(records[-1].read_text())
    hive = record["hive"]
    result = {
        "task": name, "kind": task["kind"],
        "hive": {"name": f"{record['queen']['name']} + {record['workers']['name']}", "cost_usd": hive["cost_usd"],
                 "passed": record["acceptance"]["passed"], "duration_ms": hive["duration_ms"],
                 "briefs": len(hive["briefs"]), "returns": hive["returns"],
                 "review": (record.get("summary") or {}).get("review")},
        "solo": [{"name": c["name"], "cost_usd": c.get("cost_usd"), "passed": c.get("passed"),
                  "duration_ms": c.get("duration_ms"), "error": c.get("error")} for c in record.get("compare", [])],
    }
    print(f"  hive {'✅' if result['hive']['passed'] else '❌'} ${hive['cost_usd'] or 0:.2f} · "
          + " · ".join(f"{s['name']} {'✅' if s['passed'] else '❌'} ${s['cost_usd'] or 0:.2f}" for s in result["solo"]),
          flush=True)
    return result


def table(results: list[dict]) -> str:
    def cell(variant: dict) -> str:
        mark = "✅" if variant.get("passed") else "❌"
        cost = f"${variant['cost_usd']:.2f}" if variant.get("cost_usd") is not None else "–"
        mins = f"{variant['duration_ms'] / 60000:.1f}m" if variant.get("duration_ms") else "–"
        return f"{mark} {cost} · {mins}"

    solos = [s["name"] for s in next((r["solo"] for r in results if r.get("solo")), [])]
    queen = QUEEN.replace("-", " ").title()
    lines = [f"| Task | Hive ({queen} Queen + Haiku 5.5 bees) | " + " | ".join(f"{n} alone" for n in solos) + " |",
             "|---|---|" + "---|" * len(solos)]
    totals = {"hive": [0.0, 0], **{n: [0.0, 0] for n in solos}}
    for r in results:
        if r.get("error"):
            lines.append(f"| {r['task']} ({r['kind']}) | {r['error']} |" + " |" * len(solos))
            continue
        by_name = {s["name"]: s for s in r["solo"]}
        lines.append(f"| {r['task']} ({r['kind']}) | {cell(r['hive'])} | "
                     + " | ".join(cell(by_name.get(n, {})) for n in solos) + " |")
        for key, variant in [("hive", r["hive"]), *((n, by_name.get(n, {})) for n in solos)]:
            totals[key][0] += variant.get("cost_usd") or 0
            totals[key][1] += bool(variant.get("passed"))
    done = sum(1 for r in results if not r.get("error"))
    lines.append(f"| **Total** | **{totals['hive'][1]}/{done} passed · ${totals['hive'][0]:.2f}** | "
                 + " | ".join(f"**{totals[n][1]}/{done} passed · ${totals[n][0]:.2f}**" for n in solos) + " |")
    return "\n".join(lines)


def main() -> None:
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = BENCH / f"results{TAG}.json"
    results = json.loads(path.read_text()) if path.exists() else []
    if "--table" not in sys.argv:
        for name in names or sorted(p.name for p in (BENCH / "tasks").iterdir() if p.is_dir()):
            results = [r for r in results if r["task"] != name] + [run(name)]
            path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    order = sorted(p.name for p in (BENCH / "tasks").iterdir() if p.is_dir())
    results.sort(key=lambda r: order.index(r["task"]) if r["task"] in order else 99)
    (BENCH / f"RESULTS{TAG}.md").write_text(f"# Benchmark results{(' · Queen ' + QUEEN) if TAG else ''}\n\n"
                                            + table(results) + "\n")
    print("\n" + table(results))


if __name__ == "__main__":
    main()
