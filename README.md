# 🐝 The Hive

A Queen model plans, writes briefs and checks the work. Cheap **Haiku worker bees** build, scout and review. It works on any folder and any stack, with goals in any language. An **independent review** runs after every job, and the **statistics** show what the job cost compared with a single model doing it alone.

```
hive "Fix the failing tests in ~/projects/api"
```

`hive` opens Claude Code with the Queen's rules and the bees loaded, so you work in the interface you already know. When you exit, it checks the result and reports each job:

```
🐝 Hive (Claude Opus 5.5 + Claude Haiku 5.5)   ✅   $0.41   2.1m
   └ queen  ≈$0.36 · build ≈$0.01 · review ≈$0.04
acceptance ✅ $ npm test
🐝 Hive $0.41 vs Claude Opus 5.5 alone $0.97 (measured) → saved 58%
```

## Requirements

- **Python 3.10 or newer**
- **macOS or Linux**
- **Claude Code** ([install](https://code.claude.com)) with your login, or an `ANTHROPIC_API_KEY`. Without Claude Code installed, install the hive with its own copy: `pip install -e ".[bundled]"`.

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
hive                         # pick a folder, then work in Claude Code
hive "Explain how this project is structured" -d ~/some/project
hive "Add a /health endpoint" --headless --done "npm test"   # scripts and CI: no interface, stops at the end
hive dashboard               # live view, history, comparisons (runs in the background)
hive dashboard down          # stop the dashboard
```

The Hive signs in with your Claude Code login or `ANTHROPIC_API_KEY`.

## What you get

- **Choose your Queen:** Fable 5.1, Opus 5.5, Sonnet 5.5, Opus 4.8 and others. Bees are Haiku 5.5 by default, and any kind of bee can run on another model, including a **local model** through Ollama (`--scout qwen-coder`).
- **Runs in Claude Code itself:** `hive` opens the normal Claude Code interface with the Queen's rules and the bees loaded, then reports and records each job when you exit. Scripts and CI get a headless mode (`--headless`), and there's also a `/haiku-hive:hive` plugin command.
- **Autonomy modes:** `plan` (you approve the briefs), `auto`, or `ask` (risky actions need a y/n).
- **Briefs with "Done when":** every brief comes with a runnable check. The Queen re-runs each check herself and returns a brief at most 3 times before asking you.
- **Independent review:** Haiku reviewers check the finished work from separate lenses (goal, correctness, tests, architecture, performance, rules, security). They don't see the builders' reports. `hive review` runs the same review on any diff, branch or PR.
- **Protected paths:** for example your acceptance tests. A hook blocks file edits to them, and shell writes as far as a parse of the command can tell.
- **Memory outside your project:** kept in `~/.hive/projects/…`. After each job, a retro (`waggle`) proposes rule fixes and applies only those you approve. Skip it with `--no-waggle`.
- **Statistics:** tokens and cost per stage. Each job is compared with single models, either estimated or, with `--compare`, as real side-by-side runs.

## Safety: what is enforced and what isn't

- **Permissions are Claude Code's.** Edits outside the granted folders need your approval. In `auto` mode, shell commands run without asking. Use `ask` mode, or `--sandbox` (Claude Code's Bash sandbox: writes only inside the granted folders), on machines that matter.
- **Hooks are guards, not a sandbox.** The protected-path and read-only-bee checks parse shell commands; a command such as `python -c "…"` can write without being noticed. `--sandbox` is the real boundary.
- **Acceptance commands run on your machine.** After a session the hive itself runs the acceptance commands with your shell, outside Claude Code's permissions. Yours (`--done`, the profile's `test` command) always run. The Queen's own run automatically only in `plan` and `auto` mode without `--sandbox`, where she could have run them in the session anyway. In `ask` mode or with `--sandbox` you're asked first (default no), and headless runs skip them.
- **Memory feeds every later session.** The Queen writes `known-issues.md`, `decisions.md` and `progress.md`, and they go into her instructions next time. The end-of-session report lists every line she added (📝), so you can catch an instruction planted by code you don't trust.
- **`--compare` copies are contained.** Links that lead out of a copy are removed, and with `--sandbox` the solo models run sandboxed too.
- **Everything stays local.** Memory, run logs and the dashboard never leave your machine. The dashboard listens on `127.0.0.1` and answers only its own pages, so other websites can't read it or trigger paid model checks. Local models get no login headers.

📖 **Full guide: [docs/GUIDE.md](docs/GUIDE.md)**
