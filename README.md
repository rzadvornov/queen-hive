# 🐝 The Hive

A Queen model plans, writes briefs and checks the work. Cheap **Haiku worker bees** build, scout and review. It works on any folder and any stack, with goals in any language. An **independent review** runs after every job, and the **statistics** show what the job cost compared with a single model doing it alone.

```
hive "Fix the failing tests in ~/projects/api"
```

```
👑 Queen: Claude Opus 5.5 · 🐝 bees: Claude Haiku 5.5 · mode: auto · review: full
👑 → 🔨 builder   B1 fix date parsing
👑 🔍 $ npm test
   ✅ Tests: 42 passed
👑 → 🧐 reviewer  R-correctness review fix
👑 → 🧐 reviewer  R-arch review fix
...
🐝 Hive $0.41 vs Claude Opus 5.5 alone $0.97 (measured) → saved 58%
```

## Requirements

- **Python 3.10 or newer**
- **macOS or Linux**
- A Claude Code login or an `ANTHROPIC_API_KEY`. You don't need to install Claude Code, because the SDK ships its own copy of the CLI.

### Check your Python version

```bash
python3 --version
```

You need `Python 3.10.x` or higher. If you see `command not found` or a version below 3.10 (macOS ships 3.9 with the Xcode tools), install a newer Python:

| OS | Install a newer Python |
|---|---|
| macOS | `brew install python@3.12`, or the installer from [python.org](https://www.python.org/downloads/) |
| Ubuntu / Debian | `sudo apt update && sudo apt install python3.12 python3.12-venv`. On older releases, add the `deadsnakes` PPA first: `sudo add-apt-repository ppa:deadsnakes/ppa` |
| Fedora | `sudo dnf install python3.12` |
| Any OS | [pyenv](https://github.com/pyenv/pyenv): `pyenv install 3.12` then `pyenv local 3.12` in the repo |

The new version usually doesn't replace `python3`. Call it by its full name when you create the venv, for example `python3.12 -m venv .venv`. After that, the venv always uses that version. If `pip install -e .` says `requires a different Python`, the venv was built with an old Python. Delete it (`rm -rf .venv`) and create it again with the newer one.

## Quick start

### macOS and Linux

```bash
git clone <this repo> ~/the-hive && cd ~/the-hive
python3 -m venv .venv            # or python3.12 -m venv .venv, see above
.venv/bin/pip install -e .
.venv/bin/hive --help            # check that it works
```

Put `hive` on your PATH, either with a symlink or by adding the venv's `bin` folder:

```bash
ln -s ~/the-hive/.venv/bin/hive /usr/local/bin/hive                      # macOS (may need sudo)
mkdir -p ~/.local/bin && ln -s ~/the-hive/.venv/bin/hive ~/.local/bin/hive  # Linux, if ~/.local/bin is on PATH
```

### First run

```bash
hive models --check          # which Queens your login can use
hive "Explain how this project is structured" -d ~/some/project
hive dashboard               # live view, history, comparisons (runs in the background)
hive dashboard down          # stop the dashboard
```

The Hive signs in with your Claude Code login or `ANTHROPIC_API_KEY`.

## What you get

- **Choose your Queen:** Fable 5.1, Opus 5.5, Sonnet 5.5, Opus 4.8 and others. Bees are Haiku 5.5.
- **Three ways to run it:** a one-shot CLI, `hive chat`, and the `/haiku-hive:hive` Claude Code plugin.
- **Autonomy modes:** `plan` (you approve the briefs), `auto`, or `ask` (risky actions need a y/n).
- **Briefs with "Done when":** every brief comes with a runnable check. The Queen re-runs each check herself and returns a brief at most 3 times before asking you.
- **Independent review:** Haiku reviewers check the finished work from separate lenses (goal, correctness, tests, architecture, performance, rules, security). They don't see the builders' reports.
- **Protected paths:** for example your acceptance tests. A hook blocks any edit to them.
- **Memory outside your project:** kept in `~/.hive/projects/…`. After each job, a retro (`waggle`) proposes rule fixes and applies only those you approve. Skip it with `--no-waggle`.
- **Statistics:** tokens and cost per stage. Each job is compared with single models, either estimated or, with `--compare`, as real side-by-side runs.

📖 **Full guide: [docs/GUIDE.md](docs/GUIDE.md)**
