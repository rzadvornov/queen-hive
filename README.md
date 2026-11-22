# 🐝 The Hive

A Queen model plans, writes briefs and checks the work. Cheap **worker bees** build, scout and review. It runs on **Claude** (in Claude Code), **GPT** (in OpenAI's Codex CLI) or **Gemini** (in the Gemini CLI). It works on any folder and any stack, with goals in any language. An **independent review** runs after every job, and the **statistics** show what the job cost compared with a single model doing it alone.

```
hive "Fix the failing tests in ~/projects/api"
```

`hive` opens your provider's own CLI with the Queen's rules and the bees loaded, so you work in the interface you already know. When you exit, it checks the result and reports each job:

```
🐝 Hive (Claude Opus 5.5 + Claude Haiku 5.5)   ✅   $0.41   2.1m
   └ queen  ≈$0.36 · build ≈$0.01 · review ≈$0.04
acceptance ✅ $ npm test
🐝 Hive $0.41 vs Claude Opus 5.5 alone $0.97 (measured) → saved 58%
```

## Requirements

- **Python 3.10 or newer**
- **macOS or Linux**
- The CLI of at least one AI, signed in: Claude Code, the Codex CLI or the Gemini CLI. See [Provider setup](#provider-setup).

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
hive                         # first run: pick Claude, GPT or Gemini, then a folder
hive doctor                  # is the provider's CLI installed and signed in?
hive models --check          # which models your login can use
hive "Explain how this project is structured" -d ~/some/project
hive "Add a /health endpoint" --headless --done "npm test"   # scripts and CI: no interface, stops at the end
hive dashboard               # live view, history, comparisons (runs in the background)
hive dashboard down          # stop the dashboard
```

## Provider setup

The first `hive` asks which AI runs the hive and remembers the answer, so it doesn't ask again:

```
🤖 Which AI should run the hive? (change it later with `hive provider`)
  ❯ 1) Claude  Claude Code
    2) GPT     Codex CLI
    3) Gemini  Gemini CLI
```

| Change it | Command |
|---|---|
| Switch for good | `hive provider gpt` (or `claude`, `gemini`); `hive provider` alone shows the menu |
| One run only | `hive "…" --provider gemini` |
| Pick by model | `hive "…" --queen gpt-5.4` uses that model's provider |

Each provider remembers its own last Queen and bee model. A Queen and her bees always come from one provider.

| Provider | Default Queen | Default bees |
|---|---|---|
| Claude | Claude Opus 5.5 | Claude Haiku 5.5 |
| GPT | GPT-5.5 with an API key; with a ChatGPT plan, the plan's own model (for example GPT-5.6-Terra) | GPT-6 Luna |
| Gemini | Gemini 3.1 Pro | Gemini 3.5 Flash-Lite |

All bees get the Haiku bees' settings, taken from the plugin's `agents/*.md`: medium effort (in the Gemini CLI, a medium thinking level), and in Codex compaction at 100k tokens.

### Claude (Claude Code)

1. Install [Claude Code](https://code.claude.com), or use the hive's own copy: `.venv/bin/pip install -e ".[bundled]"`.
2. Sign in: run `claude` and `/login`, or set `ANTHROPIC_API_KEY`.
3. `hive provider claude`, then `hive doctor`.

### GPT (Codex CLI)

1. Install it: `npm install -g @openai/codex`.
2. Sign in: `codex login` (ChatGPT plan), or set `OPENAI_API_KEY`.
3. `hive provider gpt`, then `hive models --check`. A ChatGPT plan can't use the API models (GPT-5.5 …). The hive adds the models your plan offers (it reads them from Codex) and uses them by default.
4. **Approve the hive's hooks once.** Codex runs hooks only after you approve them, and the hive's hooks guard protected paths, keep reviewers read-only and write the live log. Run this from any folder, approve the hooks when Codex asks (or type `/hooks`), then quit:
   ```bash
   CODEX_HOME=~/.hive/codex codex
   ```
   Until you do, GPT runs don't guard protected paths: in a test, a GPT run wrote a protected `.env`, and once the hooks were approved the same write was blocked. `hive` warns on each GPT run until then.
5. `hive doctor` should show `hooks: approved`.

If Codex keeps your login in the system keychain rather than in `~/.codex/auth.json`, sign in once for the hive: `CODEX_HOME=~/.hive/codex codex login`.

### Gemini (Gemini CLI)

1. Install it: `npm install -g @google/gemini-cli`.
2. Create an API key in [Google AI Studio](https://aistudio.google.com/apikey) and export it in your shell's startup file:
   ```bash
   echo 'export GEMINI_API_KEY="…"' >> ~/.zshrc     # bash: ~/.bashrc
   ```
   Google no longer serves the Gemini CLI to personal Google logins, so the key (or Vertex AI credentials) is needed. Put it in `~/.zshrc` rather than only `~/.zprofile`, which some terminals and tools don't read.
3. `hive provider gemini`, then `hive models --check`.
4. `hive doctor` warns if `GEMINI_API_KEY` isn't set.

### Where provider settings live

| What | Where |
|---|---|
| Your provider choice and last models | `~/.hive/state.json` |
| The hive's Codex home (bees, hooks, skills, sessions; your login linked in) | `~/.hive/codex` |
| The hive's Gemini home (one folder per session in `sessions/`, chat logs shared in `.gemini/tmp`) | `~/.hive/gemini` |
| Your own prices and local models | `~/.hive/models.json` |

Your own `~/.codex` and `~/.gemini` are never edited. GPT and Gemini prices come from price trackers, not the providers' pages, and models a ChatGPT plan offers show as $0 because a plan isn't billed per token. Set your own prices in `~/.hive/models.json` (the numbers below are only an example):

```json
{"prices": {"gpt-5.6-terra": {"input": 2, "output": 12, "cache_read": 0.2}}}
```

### Claude, GPT and Gemini compared

| | Claude | GPT | Gemini |
|---|---|---|---|
| Runs in | Claude Code | Codex CLI | Gemini CLI |
| Cost in the report | exact, from Claude Code | estimated from tokens × list price ($0 on a ChatGPT plan) | estimated from tokens × list price |
| Protected paths | hook | hook, once approved | hook |
| Read-only scouts | hook | Codex sandbox (read-only role) | tool list (no write or shell tools) |
| Read-only reviewers | hook | hook, once approved | instructions only (the CLI doesn't say which bee runs a tool) |
| Live log | bees when they start and report, commands with ✅/❌ | bees when they report, commands without ✅/❌ (Codex's hooks don't say either) | bees when they start and report, commands with ✅/❌ |
| Network for commands | yes | in `plan` and `auto` mode; not in `ask` mode or with `--sandbox` | yes |
| `--budget` cap, `--compare`, local bees | yes | no | no |

> GPT and Gemini have been run against signed-in CLIs (Codex 0.171, Gemini CLI 0.65) on small jobs only, so expect rough edges and run `hive doctor` first.

## What you get

- **Choose your AI and your Queen:** Claude (Fable 5.1, Opus 5.5, Sonnet 5.5 …), GPT (GPT-5.5, GPT-5.4 …, or your ChatGPT plan's models) or Gemini (Gemini 3.1 Pro, 3.8 Flash …). Any kind of bee can run on another model of the same provider (`--scout`, `--builder`, `--reviewer`). With Claude, a bee can also run on a **local model** through Ollama (`--scout qwen-coder`).
- **Runs in the CLI itself:** `hive` opens Claude Code, Codex or the Gemini CLI with the Queen's rules, the bees, the hooks and the skills loaded, then reports and records each job when you exit. Scripts and CI get a headless mode (`--headless`). In Claude Code there's also a `/haiku-hive:hive` plugin command.
- **👑 and 🐝 in the chat:** on every provider the Queen starts her messages with 👑 and names bees with their icon (🔎 scout, 🔨 builder, 🧐 reviewer), and bees start their reports with `🐝 <brief ID>`. The Gemini CLI shows bees as "🔎 Scout bee" and so on; Codex as "Scout bee" (it allows no emoji in names).
- **Autonomy modes:** `plan` (you approve the briefs), `auto`, or `ask` (risky actions need a y/n).
- **Briefs with "Done when":** every brief comes with a runnable check. The Queen re-runs each check herself and returns a brief at most 3 times before asking you.
- **Independent review:** reviewer bees check the finished work from separate lenses (goal, correctness, tests, architecture, performance, rules, security). They don't see the builders' reports. `hive review` runs the same review on any diff, branch or PR.
- **Protected paths:** for example your acceptance tests. A hook blocks file edits to them, and shell writes as far as a parse of the command can tell.
- **Memory outside your project:** kept in `~/.hive/projects/…`. After each job, a retro (`waggle`) proposes rule fixes and applies only those you approve. Skip it with `--no-waggle`.
- **Statistics:** tokens and cost per stage. Each job is compared with single models, either estimated or, with `--compare` (Claude only for now), as real side-by-side runs.

## Safety: what is enforced and what isn't

- **Permissions are the CLI's.** In Claude Code, edits outside the granted folders need your approval, and in `auto` mode shell commands run without asking. Use `ask` mode, or `--sandbox` (writes only inside the granted folders), on machines that matter. Codex always sandboxes commands to the granted folders, with network in `plan` and `auto` mode only. The Gemini CLI runs them unsandboxed unless you pass `--sandbox`. In a headless run in `ask` mode, Claude Code and the Gemini CLI refuse risky actions; Codex runs them inside its sandbox.
- **Your code goes to the provider you chose:** Anthropic, OpenAI or Google, under that provider's terms.
- **Hooks are guards, not a sandbox.** The protected-path and read-only-bee checks parse shell commands; a command such as `python -c "…"` can write without being noticed. `--sandbox` is the real boundary. On GPT the hooks only run once you've approved them (see [GPT setup](#gpt-codex-cli)).
- **Acceptance commands run on your machine.** After a session the hive itself runs the acceptance commands with your shell, outside the CLI's permissions. Yours (`--done`, the profile's `test` command) always run. The Queen's own run automatically only in `plan` and `auto` mode without `--sandbox`, where she could have run them in the session anyway. In `ask` mode or with `--sandbox` you're asked first (default no), and headless runs skip them.
- **Memory feeds every later session.** The Queen writes `known-issues.md`, `decisions.md` and `progress.md`, and they go into her instructions next time. The end-of-session report lists every line she added (📝), so you can catch an instruction planted by code you don't trust.
- **`--compare` copies are contained.** Links that lead out of a copy are removed, and with `--sandbox` the solo models run sandboxed too.
- **Only the Queen changes the hive.** Retro edits to the hive's rules and bees are applied by the Queen after you approve them; the protect hook denies any bee that tries (except in the Gemini CLI, which doesn't say which bee is calling).
- **Everything stays local.** Memory, run logs and the dashboard never leave your machine, and `~/.hive` is owner-only. The dashboard listens on `127.0.0.1` and answers only its own pages, so other websites can't read it or trigger paid model checks. Local models get no login headers.

📖 **Full guide: [docs/GUIDE.md](docs/GUIDE.md)**
