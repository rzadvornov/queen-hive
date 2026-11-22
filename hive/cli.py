"""The `hive` command."""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from hive import PLUGIN_DIR, __version__, memory, models, providers, stats
from hive.modes import MODES

SUBCOMMANDS = ("run", "review", "init", "models", "provider", "stats", "dashboard", "waggle", "retro", "doctor",
               "install-plugin")

EPILOG = """In a terminal, the hive opens your provider's CLI (Claude Code, Codex or the Gemini CLI) with the Queen's
rules and the bees loaded. The first run asks which one; `hive provider` changes it.
Without a terminal (scripts, CI), or with --headless, it runs the goal on its own and prints progress.

examples:
  hive                                         # pick a folder, then work in Claude Code
  hive "Fix the failing tests in ~/projects/api"
  hive "Объясни, как устроен этот проект" --mode auto
  hive "Add a /health endpoint" --headless --done "npm test"
  hive "Add a /health endpoint" --queen fable-5.1 --compare sonnet-5.5,opus-5.5
  hive "Add a /health endpoint" --provider gemini
  hive stats

other commands: review, init, models, provider, stats, dashboard, waggle (alias retro), doctor, install-plugin
run `hive <command> -h` for details."""


def _job_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-d", "--dir", type=Path, action="append", default=[],
                        help="folder to grant access to (repeatable). Default: folders named in the goal, else asked in a terminal (Enter = the current folder).")
    parser.add_argument("--provider", choices=list(providers.PROVIDERS),
                        help="AI for this run only: claude, gpt or gemini. Default: your saved choice (`hive provider`).")
    parser.add_argument("--queen", help=f"Queen model ({', '.join(m.key for m in models.queens(None))}). "
                                        "Default: the last one for the provider.")
    parser.add_argument("--workers", default=None, help="worker bee model. Default: the last one, else the provider's "
                                                        f"cheapest ({', '.join(w for _, w in models.DEFAULTS.values())}).")
    parser.add_argument("--mode", choices=list(MODES), help="autonomy mode. Default: the last one.")
    for bee in ("scout", "builder", "reviewer"):
        parser.add_argument(f"--{bee}", metavar="MODEL", help=f"model for the {bee} bees only, e.g. a local model "
                                                              "from `hive models add` (default: the bee model).")
    parser.add_argument("--review", choices=["full", "light", "off"], default="full", help="independent review level (default full).")
    parser.add_argument("--lenses", help="comma-separated review lenses, e.g. goal,correctness,tests,arch,perf,rules,security")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="hard spending cap in USD per headless run and per --compare run (default 5; Claude only).")
    parser.add_argument("--no-init", action="store_true", help="don't draft a project profile on first use.")
    parser.add_argument("--no-waggle", action="store_true", help="don't run the retro (waggle) after each finished job.")
    parser.add_argument("--sandbox", action="store_true",
                        help="run shell commands in the CLI's sandbox: writes only inside the granted folders and temp "
                             "(Claude Code also limits the network). Codex always sandboxes them.")


def _choose(args, goal: str = "", ask_folder: bool = False):
    """Resolve folders, Queen, workers and mode, asking only for what wasn't given.

    The provider comes first: --provider, else the provider of --queen, else the saved choice, asked once.
    With ask_folder, the folder is asked when neither -d nor the goal names one."""
    from hive import folders as folders_mod, init, ui
    from hive.models import choose_queen, choose_workers
    from hive.modes import DEFAULT_MODE, choose_mode

    provider = providers.current(args.provider or (models.get(args.queen).provider if args.queen else None))
    if provider != "claude":
        providers.binary(provider)   # fail early, with how to install it
    named = args.dir or folders_mod.folders_in(goal)
    default = folders_mod.ask_folder(Path.cwd()) if ask_folder and not named else Path.cwd()
    folders = folders_mod.resolve(goal, args.dir, default)
    if not args.no_init:
        asyncio.run(init.run(folders[0], use_ai=provider == "claude"))   # the others' Queens draft it with the init skill
    state = memory.load_state()
    last_queen, last_workers = models.remembered(state, provider)
    queen = _of_provider(args.queen, provider, "--queen") or last_queen
    workers = _of_provider(args.workers, provider, "--workers") or last_workers
    mode = args.mode or state.get("last_mode") or DEFAULT_MODE
    if not args.queen and models.is_available(state, queen) is False:
        queen = next((m for m in models.queens(provider) if models.is_available(state, m) is not False), queen)
    asked = not (args.queen and args.workers and args.mode)
    who = providers.PROVIDERS[provider]
    if asked and not ui.confirm(f"Run with {who.name} ({who.product}): 👑 {queen.name} · 🐝 {workers.name} bees · "
                                f"🛡  mode {mode}?"):
        queen = queen if args.queen else choose_queen(queen.key, provider)
        workers = workers if args.workers else choose_workers(workers.key, provider)
        mode = args.mode or choose_mode(mode)
    if models.is_available(state, queen) is False:
        print(f"⚠️  {queen.name} was not available last time it was checked (`hive models --check` re-checks).")
    models.remember(state, queen, workers)
    state["last_mode"] = mode
    memory.save_state(state)
    return folders, queen, workers, mode


def _of_provider(key: str | None, provider: str, flag: str) -> models.Model | None:
    """A model given on the command line, which must run in the provider's CLI."""
    if not key:
        return None
    model = models.get(key)
    if model.provider != provider and not (model.local and provider == "claude"):
        raise SystemExit(f"{flag} {model.key} is a {providers.PROVIDERS[model.provider].name} model, but this run uses "
                         f"{providers.PROVIDERS[provider].name}. Pick one of: "
                         f"{', '.join(m.key for m in models.catalog(provider))}, or add --provider {model.provider}.")
    return model


def cmd_run(argv: list[str]) -> None:
    from hive import launch, ui
    from hive.job import Job

    parser = argparse.ArgumentParser(prog="hive", description="Run the hive: a Queen model and cheap worker bees, "
                                                              "in Claude Code, Codex or the Gemini CLI.",
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("goal", nargs="?", default="",
                        help="what you want done (optional in a terminal). Folders mentioned here are granted access.")
    _job_args(parser)
    parser.add_argument("--done", action="append", default=[], metavar="CMD",
                        help="acceptance command that must pass (repeatable). Default: the Queen's final checks or the profile's test command.")
    parser.add_argument("--compare", nargs="?", const="default", metavar="MODELS",
                        help=f"also run the goal with single models alone in copies of the folder "
                             f"(default {','.join(models.DEFAULT_COMPARE)}; 'all' = every available Queen model).")
    parser.add_argument("--yes", action="store_true", help="don't ask to confirm --compare costs.")
    parser.add_argument("--headless", action="store_true",
                        help="run the goal without the CLI's interface and stop at the end (the default without a terminal).")
    parser.add_argument("--version", action="version", version=f"hive {__version__}")
    args = parser.parse_args(argv)

    headless = args.headless or not ui.interactive()
    if headless and not args.goal:
        parser.error("a goal is required for a headless run (no terminal, or --headless)")
    if args.compare and not args.goal:
        parser.error("--compare needs a goal")
    folders, queen, workers, mode = _choose(args, args.goal, ask_folder=not headless)
    if args.compare and queen.provider != "claude":
        raise SystemExit("--compare runs Claude models only for now.")
    roles = _roles(args, queen.provider)
    if headless and mode != "auto":
        print(f"🛡  headless: nobody can approve a plan or a risky action, so mode {mode} runs as auto"
              + (" (risky actions are refused)." if mode == "ask" else "."))
        mode = "auto" if mode == "plan" else mode
    compare = _compare_keys(args.compare)
    if compare:
        cap = f"${args.budget:g} each" if args.budget else "no cap"
        print(f"⚖️  comparison: {', '.join(models.get(k).name for k in compare)} will each redo the job alone ({cap}).")
        if not args.yes and not _confirm("   run the comparison?"):
            compare = []
    job = Job(goal=args.goal, folders=folders, queen=queen, workers=workers, mode=mode, review=args.review,
              lenses=_split(args.lenses), done=args.done, budget=args.budget, compare=compare,
              waggle=not args.no_waggle and not headless, sandbox=args.sandbox, roles=roles)
    records = launch.run(job, headless=headless)
    if headless and not records:
        sys.exit(1)   # no job came out of it: the run failed
    last = records[-1] if records else None
    sys.exit(1 if last and (last["acceptance"]["passed"] is False or last["status"] == "failed") else 0)


def _roles(args, provider: str = "claude") -> dict:
    """Per-bee models from --scout/--builder/--reviewer."""
    return {bee: _of_provider(getattr(args, bee), provider, f"--{bee}")
            for bee in ("scout", "builder", "reviewer") if getattr(args, bee, None)}


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


def cmd_waggle(argv: list[str], prog: str) -> None:
    """A retro of the project's last run, in the provider's CLI."""
    from hive import launch
    from hive.job import Job

    parser = argparse.ArgumentParser(prog=prog, description="Retro of the project's last run, with proposed rule and memory edits.")
    parser.add_argument("note", nargs="?", default="", help="what to focus the retro on (optional).")
    _job_args(parser)
    args = parser.parse_args(argv)
    folders, queen, workers, mode = _choose(args, ask_folder=True)
    job = Job(goal=_waggle_prompt(args.note, queen.provider), folders=folders, queen=queen, workers=workers, mode=mode,
              review=args.review, lenses=_split(args.lenses), budget=args.budget, waggle=False,
              roles=_roles(args, queen.provider))
    launch.run(job)


def cmd_review(argv: list[str]) -> None:
    """An independent review of existing changes, in the provider's CLI."""
    from hive import launch
    from hive.job import Job

    parser = argparse.ArgumentParser(prog="hive review", description="Independent review of changes by reviewer bees; builds nothing.")
    parser.add_argument("target", nargs="?", default="",
                        help="what to review: nothing for uncommitted changes, a branch, a commit range, or a PR number/URL.")
    _job_args(parser)
    args = parser.parse_args(argv)
    folders, queen, workers, mode = _choose(args, ask_folder=True)
    job = Job(goal=_skill_prompt("review", args.target, queen.provider), folders=folders, queen=queen, workers=workers,
              mode=mode, review=args.review, lenses=_split(args.lenses), budget=args.budget, waggle=False,
              roles=_roles(args, queen.provider))
    launch.run(job)


def _waggle_prompt(note: str, provider: str = "claude") -> str:
    """The skill reads the last recorded run itself (scripts/lastrun.py)."""
    return _skill_prompt("waggle", f"Review the last recorded hive run in this project. {note}".strip(), provider)


def _skill_prompt(skill: str, arguments: str, provider: str) -> str:
    """A slash command in Claude Code; the other CLIs are asked to use the skill."""
    if provider == "claude":
        return f"/haiku-hive:{skill} {arguments}".strip()
    return f"Use the `{skill}` skill" + (f" with: {arguments}" if arguments else ".")


def cmd_init(argv: list[str]) -> None:
    from hive import init

    parser = argparse.ArgumentParser(prog="hive init", description="Draft or refresh a folder's hive profile.")
    parser.add_argument("folder", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--no-ai", action="store_true", help="only detect from manifest files; no scout (Claude only).")
    parser.add_argument("--force", action="store_true", help="redraft even if a profile exists.")
    args = parser.parse_args(argv)
    claude_runs = providers.current(ask=False) == "claude"   # the scout is a Claude Code bee
    if not args.no_ai and not claude_runs:
        print("   drafting from manifest files only (the scout runs in Claude Code). Answer n to keep the empty template "
              "instead, and the Queen drafts the profile with the `init` skill in your first session.")
    pdir = asyncio.run(init.run(args.folder, use_ai=not args.no_ai and claude_runs, force=args.force))
    print(f"memory folder: {pdir}")


def cmd_models(argv: list[str]) -> None:
    if argv[:1] in (["add"], ["remove"]):
        return _local_model(argv)
    parser = argparse.ArgumentParser(prog="hive models", description="Model catalog, prices and your access.",
                                     epilog="local models: hive models add KEY MODEL_ID [--url URL] · hive models remove KEY")
    parser.add_argument("--check", action="store_true", help="probe each model with a tiny request (costs a fraction of a cent).")
    parser.add_argument("--provider", choices=list(providers.PROVIDERS), help="this provider's models (default: your saved one).")
    parser.add_argument("--all", action="store_true", help="every provider's models.")
    args = parser.parse_args(argv)
    provider = providers.current(args.provider, ask=False)
    shown = list(providers.PROVIDERS) if args.all else [provider]
    if args.check:
        print("checking access…")
        for key in shown:
            asyncio.run(models.check_access(provider=key))
    state = memory.load_state()
    for key in shown:
        p = providers.PROVIDERS[key]
        queen = models.remembered(state, key)[0]
        print(f"\n{p.name} ({p.product}) · last Queen: {queen.name} · {models.prices_note(key)}")
        print(f"{'model':22} {'id':24} {'in/out $/M':12} {'role':10} access")
        for m in models.catalog(key):
            entry = models.access(state).get(m.key)
            access = "not checked" if entry is None else "✅" if entry["ok"] else f"✗ {entry.get('error', '')[:50]}"
            role = "queen" if m.queen_effort else "local bees" if m.local else "bees"
            print(f"{m.key:22} {m.id:24} {f'{m.input:g}/{m.output:g}':12} {role:10} {access}")
    if not args.check:
        print("\nRun `hive models --check` to test access" + ("" if args.all else ", `--all` for every provider") + ".")


def cmd_provider(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hive provider", description="Show or change which AI runs the hive.")
    parser.add_argument("name", nargs="?", help="claude, gpt or gemini. Without it: show the providers and pick one.")
    args = parser.parse_args(argv)
    from hive import ui

    if args.name:
        key = providers.get(args.name).key
        providers.save(key)
    elif ui.interactive():
        key = providers.choose()
    else:
        key = providers.saved()
        for p in providers.PROVIDERS.values():
            mark = "❯" if p.key == key else " "
            print(f"{mark} {p.key:7} {p.name:7} {p.product:12} " + ("installed" if providers.installed(p.key) else
                                                                    f"not installed: {p.install}"))
        print("" if key else "no provider chosen yet: the next `hive` asks.")
        return
    p = providers.PROVIDERS[key]
    queen, workers = models.remembered(memory.load_state(), key)
    print(f"🤖 the hive now runs on {p.name} ({p.product}): 👑 {queen.name} · 🐝 {workers.name} bees.")
    if not providers.installed(key):
        print(f"   {p.product} isn't installed yet: {p.install}, then sign in: {p.login}")


def _local_model(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog=f"hive models {argv[0]}", description="Add or remove a local model for bees.")
    parser.add_argument("key", help="short name for --scout/--builder/--reviewer/--workers, e.g. qwen-coder")
    if argv[0] == "add":
        parser.add_argument("model_id", help="the model as the server names it, e.g. qwen2.5-coder:14b")
        parser.add_argument("--url", default=models.OLLAMA_URL, help=f"Anthropic-compatible server (default {models.OLLAMA_URL})")
        parser.add_argument("--name", help="display name")
    args = parser.parse_args(argv[1:])
    if argv[0] == "remove":
        print(f"removed {args.key}" if models.remove_local(args.key) else f"no local model called {args.key}")
        return
    model = models.add_local(args.key, args.model_id, args.url, args.name)
    print(f"added {model.key}: {model.id} at {model.base_url}. Check it with `hive models --check`, "
          f"then use it with e.g. `--scout {model.key}`.")


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
    stats.print_history(args.folder.expanduser().resolve() if args.folder else None)


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
    from hive import claude

    chosen = providers.saved()
    print(f"provider: {providers.PROVIDERS[chosen].name if chosen else 'not chosen yet (the next `hive` asks)'}")
    for key in ("gpt", "gemini"):
        _provider_check(key, key == chosen)
    try:
        binary = claude.binary()
    except SystemExit as missing:
        print(f"{'⚠️  ' if chosen in (None, 'claude') else ''}Claude Code: {missing}")
        print(f"hive {__version__} · python {sys.version.split()[0]} · hive home: {memory.hive_home()}")
        return
    version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"hive {__version__} · Claude Code {version or '?'} ({binary}) · python {sys.version.split()[0]}")
    out = subprocess.run([binary, "plugin", "validate", str(PLUGIN_DIR)], capture_output=True, text=True)
    lines = (out.stdout + out.stderr).strip().splitlines()
    print("plugin validate: " + (lines[-1] if lines else "?"))
    print(f"plugin: {PLUGIN_DIR}")
    installed = claude.installed_plugins("haiku-hive")
    if installed:
        print(f"installed in Claude Code too: {', '.join(installed)} (switched off inside `hive` sessions)")
    print(f"hive home: {memory.hive_home()}")
    for leftover in ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_EFFORT_LEVEL"):
        if os.environ.get(leftover):
            print(f"⚠️  {leftover} is set and overrides per-bee settings")
    print(_transcript_check())
    print(json.dumps(memory.load_state().get("access", {}), indent=1) if memory.load_state().get("access") else
          "model access: not checked (run `hive models --check`)")


def _provider_check(key: str, chosen: bool) -> None:
    p = providers.PROVIDERS[key]
    if not providers.installed(key):
        if chosen:
            print(f"⚠️  {p.product} is not installed: {p.install}")
        return
    binary = providers.binary(key)
    version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
    line = f"{p.product} {version or '?'} ({binary})"
    if key == "gpt":
        from hive import codex

        line += f" · login (hive's Codex home {codex.home()}): {codex.login_status()}"
        line += ("\n   hooks: approved" if codex.hooks_trusted() else
                 "\n⚠️  hooks: not approved, so protected paths aren't guarded: " + codex.TRUST_HINT.format(home=codex.home()))
    else:
        from hive import gemini

        line += f" · hive's Gemini home: {gemini.home()}" + ("" if os.environ.get("GEMINI_API_KEY") else
                                                              " · GEMINI_API_KEY not set")
    print(line)


def _transcript_check() -> str:
    """Read the last run's Claude Code transcript again: the stats depend on its format, which isn't a stable API."""
    from hive import transcript

    runs = [r for r in stats.load_runs(memory.all_projects())
            if r.get("session_id") and r.get("provider", "claude") == "claude"]
    if not runs:
        return "transcripts: no recorded session yet"
    path = transcript.locate(runs[-1]["session_id"])
    if not path:
        return "transcripts: the last run's transcript is gone (Claude Code may have cleaned it up)"
    traces, exact = transcript.jobs(path)
    tokens = sum(t.input + t.output for trace in traces for t in trace.tracker.usage.values())
    if not traces or not tokens:
        return ("⚠️  transcripts: the last session reads as empty. Claude Code's transcript format may have changed, "
                "so hive statistics will be wrong until hive/transcript.py is updated.")
    return f"transcripts: ok (last session: {len(traces)} job(s), {tokens:,} tokens" + (f", ${exact:.2f})" if exact else ")")


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
    if not argv:
        cmd_run([])
        return
    first, rest = argv[0], argv[1:]
    if first == "--version":
        print(f"hive {__version__}")
    elif first == "run":
        cmd_run(rest)
    elif first == "chat":
        raise SystemExit("`hive chat` was removed: run `hive` (add -d DIR or a goal), which opens Claude Code with the hive loaded.")
    elif first == "review":
        cmd_review(rest)
    elif first in ("waggle", "retro"):
        cmd_waggle(rest, prog=f"hive {first}")
    elif first == "init":
        cmd_init(rest)
    elif first == "models":
        cmd_models(rest)
    elif first == "provider":
        cmd_provider(rest)
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
