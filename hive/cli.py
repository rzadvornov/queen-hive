"""The `hive` command."""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from hive import PLUGIN_DIR, __version__, memory, models, stats
from hive.modes import MODES

SUBCOMMANDS = ("run", "chat", "init", "models", "stats", "dashboard", "waggle", "retro", "doctor", "install-plugin")

EPILOG = """examples:
  hive "Fix the failing tests in ~/projects/api"
  hive "Объясни, как устроен этот проект" --mode auto
  hive "Add a /health endpoint" --queen fable-5.1 --compare sonnet-5.5,opus-5.5
  hive chat -d ~/projects/api
  hive stats

other commands: chat, init, models, stats, dashboard, waggle (alias retro), doctor, install-plugin
run `hive <command> -h` for details."""


def _job_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-d", "--dir", type=Path, action="append", default=[],
                        help="folder to grant access to (repeatable). Default: folders named in the goal, else the current folder.")
    parser.add_argument("--queen", help=f"Queen model ({', '.join(m.key for m in models.queens())}). Asked if omitted.")
    parser.add_argument("--workers", default=None, help=f"worker bee model (default {models.DEFAULT_WORKERS}).")
    parser.add_argument("--mode", choices=list(MODES), help="autonomy mode. Asked if omitted.")
    parser.add_argument("--review", choices=["full", "light", "off"], default="full", help="independent review level (default full).")
    parser.add_argument("--lenses", help="comma-separated review lenses, e.g. goal,correctness,tests,arch,perf,rules,security")
    parser.add_argument("--budget", type=float, default=5.0, help="hard spending cap in USD per run (default 5).")
    parser.add_argument("-v", "--verbose", action="store_true", help="show every bee message and tool call.")
    parser.add_argument("--no-init", action="store_true", help="don't draft a project profile on first use.")


def _choose(args, goal: str = ""):
    """Resolve folders, Queen, workers and mode, asking only for what wasn't given."""
    from hive import folders as folders_mod, init
    from hive.models import choose_queen
    from hive.modes import choose_mode

    folders = folders_mod.resolve(goal, args.dir, Path.cwd())
    if not args.no_init:
        asyncio.run(init.run(folders[0]))
    state = memory.load_state()
    queen = models.get(args.queen) if args.queen else choose_queen()
    if models.is_available(state, queen) is False:
        print(f"⚠️  {queen.name} was not available last time it was checked (`hive models` re-checks).")
    workers = models.get(args.workers or state.get("workers") or models.DEFAULT_WORKERS)
    mode = args.mode or choose_mode()
    state.update(last_queen=queen.key, last_mode=mode)
    memory.save_state(state)
    return folders, queen, workers, mode


def cmd_run(argv: list[str]) -> None:
    from hive.session import Job, run_job

    parser = argparse.ArgumentParser(prog="hive", description="Run a goal through the hive.",
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("goal", help="what you want done. Folders mentioned here are granted access.")
    _job_args(parser)
    parser.add_argument("--done", action="append", default=[], metavar="CMD",
                        help="acceptance command that must pass (repeatable). Default: the Queen's final checks or the profile's test command.")
    parser.add_argument("--compare", nargs="?", const="default", metavar="MODELS",
                        help=f"also run the goal with single models alone in copies of the folder "
                             f"(default {','.join(models.DEFAULT_COMPARE)}; 'all' = every available Queen model).")
    parser.add_argument("--yes", action="store_true", help="don't ask to confirm --compare costs.")
    parser.add_argument("--version", action="version", version=f"hive {__version__}")
    args = parser.parse_args(argv)

    folders, queen, workers, mode = _choose(args, args.goal)
    compare = _compare_keys(args.compare)
    if compare:
        cap = f"${args.budget:g} each" if args.budget else "no cap"
        print(f"⚖️  comparison: {', '.join(models.get(k).name for k in compare)} will each redo the job alone ({cap}).")
        if not args.yes and not _confirm("   run the comparison?"):
            compare = []
    job = Job(goal=args.goal, folders=folders, queen=queen, workers=workers, mode=mode, review=args.review,
              lenses=_split(args.lenses), done=args.done, budget=args.budget, compare=compare, verbose=args.verbose)
    record = asyncio.run(run_job(job))
    sys.exit(0 if record["acceptance"]["passed"] is not False and record["status"] != "failed" else 1)


def _compare_keys(value: str | None) -> list[str]:
    if not value:
        return []
    state = memory.load_state()
    if value == "default":
        keys = list(models.DEFAULT_COMPARE)
    elif value == "all":
        keys = [m.key for m in models.queens()]
    else:
        keys = [models.get(k).key for k in _split(value)]
    available = [k for k in keys if models.is_available(state, models.get(k)) is not False]
    skipped = set(keys) - set(available)
    if skipped:
        print(f"⚖️  skipping models without access: {', '.join(sorted(skipped))}")
    return available


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _confirm(question: str) -> bool:
    from hive import ui

    return ui.confirm(question)


def cmd_chat(argv: list[str], first_prompt: str | None = None, prog: str = "hive chat") -> None:
    from hive.chat import chat
    from hive.session import Job

    parser = argparse.ArgumentParser(prog=prog, description="Interactive session with the Queen.")
    _job_args(parser)
    if first_prompt is not None:
        parser.add_argument("note", nargs="?", default="", help="what to focus the retro on (optional).")
    args = parser.parse_args(argv)
    folders, queen, workers, mode = _choose(args)
    job = Job(goal="", folders=folders, queen=queen, workers=workers, mode=mode, review=args.review,
              lenses=_split(args.lenses), budget=args.budget, verbose=args.verbose)
    if first_prompt is not None:
        first_prompt = _waggle_prompt(folders[0], getattr(args, "note", ""))
    asyncio.run(chat(job, first_prompt))


def _waggle_prompt(root: Path, note: str) -> str:
    runs = stats.load_runs([memory.project_dir(root)])
    if not runs:
        return f"/haiku-hive:waggle {note}".strip()
    last = runs[-1]
    events = Path(last["path"]).with_name("events.jsonl")
    return (f"/haiku-hive:waggle Review the last hive run in this project: its record is {last['path']} and its event "
            f"log is {events}. Read them to see what happened (briefs, returns, checks, review findings). {note}").strip()


def cmd_init(argv: list[str]) -> None:
    from hive import init

    parser = argparse.ArgumentParser(prog="hive init", description="Draft or refresh a folder's hive profile.")
    parser.add_argument("folder", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--no-ai", action="store_true", help="only detect from manifest files; no scout.")
    parser.add_argument("--force", action="store_true", help="redraft even if a profile exists.")
    args = parser.parse_args(argv)
    pdir = asyncio.run(init.run(args.folder, use_ai=not args.no_ai, force=args.force))
    print(f"memory folder: {pdir}")


def cmd_models(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hive models", description="Model catalog, prices and your access.")
    parser.add_argument("--check", action="store_true", help="probe each model with a tiny request (costs a fraction of a cent).")
    args = parser.parse_args(argv)
    if args.check:
        print("checking access…")
        asyncio.run(models.check_access())
    state = memory.load_state()
    print(f"{'model':12} {'id':20} {'in/out $/M':12} {'role':10} access")
    for m in models.CATALOG:
        entry = models.access(state).get(m.key)
        access = "not checked" if entry is None else "✅" if entry["ok"] else f"✗ {entry.get('error', '')[:50]}"
        role = "queen" if m.queen_effort else "bees"
        print(f"{m.key:12} {m.id:20} {f'{m.input:g}/{m.output:g}':12} {role:10} {access}")
    print(f"\nprices as of {models.PRICES_AS_OF}. Last Queen: {state.get('last_queen', '–')}. "
          + ("" if args.check else "Run `hive models --check` to test access."))


def cmd_stats(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hive stats", description="History of hive runs.")
    parser.add_argument("folder", nargs="?", type=Path, help="only this project (default: all projects).")
    parser.add_argument("--last", action="store_true", help="show the full report of the last run.")
    args = parser.parse_args(argv)
    if args.last:
        runs = stats.load_runs([memory.project_dir(args.folder)] if args.folder else memory.all_projects())
        if runs:
            stats.print_report(runs[-1])
        else:
            print("No hive runs yet.")
        return
    stats.print_history(args.folder.resolve() if args.folder else None)


def cmd_dashboard(argv: list[str]) -> None:
    from hive.dashboard import process

    parser = argparse.ArgumentParser(prog="hive dashboard", description="Local dashboard for hive runs, in a background process.")
    parser.add_argument("action", nargs="?", choices=["up", "down", "status"], default="up",
                        help="up starts it (default), down stops it, status shows whether it runs.")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--no-open", action="store_true", help="don't open the browser.")
    parser.add_argument("--foreground", action="store_true", help="run in this terminal until Ctrl-C instead.")
    args = parser.parse_args(argv)
    if args.action == "down":
        process.down()
    elif args.action == "status":
        process.status()
    elif args.foreground:
        from hive.dashboard.server import serve

        print(f"🐝 hive dashboard on http://localhost:{args.port} (Ctrl-C to stop)")
        serve(args.port, open_browser=not args.no_open)
    else:
        process.up(args.port, open_browser=not args.no_open)


def cmd_doctor(argv: list[str]) -> None:
    import claude_agent_sdk

    print(f"hive {__version__} · claude-agent-sdk {getattr(claude_agent_sdk, '__version__', '?')} · python {sys.version.split()[0]}")
    claude = shutil.which("claude")
    print(f"claude CLI on PATH: {claude or 'not found (the SDK uses its bundled copy)'}")
    if claude:
        out = subprocess.run([claude, "plugin", "validate", str(PLUGIN_DIR)], capture_output=True, text=True)
        print("plugin validate: " + (out.stdout + out.stderr).strip().splitlines()[-1] if (out.stdout + out.stderr).strip() else "?")
    print(f"plugin: {PLUGIN_DIR}")
    print(f"hive home: {memory.hive_home()}")
    for leftover in ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_EFFORT_LEVEL"):
        import os

        if os.environ.get(leftover):
            print(f"⚠️  {leftover} is set and overrides per-bee settings")
    print(json.dumps(memory.load_state().get("access", {}), indent=1) if memory.load_state().get("access") else
          "model access: not checked (run `hive models --check`)")


def cmd_install_plugin(argv: list[str]) -> None:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("claude CLI not found on PATH.")
    marketplace = PLUGIN_DIR.parent
    for cmd in ([claude, "plugin", "marketplace", "add", str(marketplace)],
                [claude, "plugin", "install", "haiku-hive@hive-local"]):
        print("$ " + " ".join(cmd), flush=True)
        subprocess.run(cmd, check=False)
    print("In Claude Code: /haiku-hive:hive <goal>, /haiku-hive:waggle or /haiku-hive:retro")


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        cmd_run(["-h"])
    first, rest = argv[0], argv[1:]
    if first == "--version":
        print(f"hive {__version__}")
    elif first == "run":
        cmd_run(rest)
    elif first == "chat":
        cmd_chat(rest)
    elif first in ("waggle", "retro"):
        cmd_chat(rest, first_prompt="", prog=f"hive {first}")
    elif first == "init":
        cmd_init(rest)
    elif first == "models":
        cmd_models(rest)
    elif first == "stats":
        cmd_stats(rest)
    elif first == "dashboard":
        cmd_dashboard(rest)
    elif first == "doctor":
        cmd_doctor(rest)
    elif first == "install-plugin":
        cmd_install_plugin(rest)
    else:
        cmd_run(argv)


if __name__ == "__main__":
    main()
