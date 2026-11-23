# Queen Hive: user guide

1. [Concepts](#1-concepts)
2. [Install and sign in](#2-install-and-sign-in)
3. [Your first run](#3-your-first-run)
4. [Commands and flags](#4-commands-and-flags)
5. [Choosing a Queen and a mode](#5-choosing-a-queen-and-a-mode)
6. [Writing good goals and Done-when checks](#6-writing-good-goals-and-done-when-checks)
7. [Any stack, any language, non-coding work](#7-any-stack-any-language-non-coding-work)
8. [Reading the statistics](#8-reading-the-statistics)
9. [The dashboard](#9-the-dashboard)
10. [The Claude Code plugin](#10-the-claude-code-plugin)
11. [Customizing bees and rules](#11-customizing-bees-and-rules)
12. [Costs and safety](#12-costs-and-safety)
13. [Troubleshooting and FAQ](#13-troubleshooting-and-faq)

---

## 1. Concepts

| Term | What it is |
|---|---|
| **👑 Queen** | The model you choose: Claude (Fable 5.1, Opus 5.5, Sonnet 5.5 …), GPT (GPT-5.5 …) or Gemini (Gemini 3.1 Pro …). It plans, writes briefs, checks results, runs the review and talks to you. It doesn't write code itself, except one- or two-line fixes. |
| **🐝 Bees** | Cheap workers from the Queen's provider: Haiku 5.5, GPT-6 Luna or Gemini 3.5 Flash-Lite by default. Any bee can run on another model of that provider, and with Claude on a local one (§11). **scout** researches, **builder** makes changes and adds tests, and **reviewer** checks finished work. Scouts and reviewers are read-only, enforced by a hook (for GPT and Gemini, see §2). |
| **Brief** | A task for one bee, at most 10 lines: *Goal / Read / Don't touch / Done when*. Each brief has an ID: `S1` (scout), `B2` (build), `R-arch` (review lens) or `F1` (fix after review). |
| **Done when** | A runnable command plus the output it must show, such as `npm test shows 0 failures`. |
| **Don't trust reports** | The Queen runs every Done-when check herself before accepting a brief. A failing brief goes back to a builder with the error output. **After 3 returns of the same brief she stops and asks you.** |
| **Independent review** | After the work is accepted, several reviewer bees check it in parallel, one *lens* each. They see only the goal, the change set and the project memory, **not** the builders' reports. The Queen triages every finding: false positives are dismissed with a reason, real defects get fix briefs, and opinions come to you as suggestions. At most 2 review rounds. |
| **Protected paths** | Files the hive must never change, typically your acceptance tests. A hook blocks every edit to them; reading and running them is fine. |
| **Project memory** | `~/.hive/projects/<folder>-<hash>/`: `profile.md` (stack, commands, protected paths), `progress.md`, `decisions.md`, `known-issues.md`, `retro-log.md` (retro proposals you approved or rejected) and `runs/`. **Nothing is written into your project.** |
| **Waggle** | A retro after a job (alias `retro`). It runs automatically when a job finishes and proposes at most 3 small edits to rules or memory, each with its evidence. It applies only the ones you approve, logs your answers and doesn't propose a rejected edit again. |

What a run looks like:

```
you ──goal──▶ 👑 Queen ──briefs──▶ 🐝 builders/scouts ──reports──▶ 👑 re-runs each Done when
                                                                         │
                       you ◀──summary + stats── 👑 triage ◀── 🐝 reviewers (in parallel, one lens each)
```

## 2. Install and sign in

Requirements: Python 3.10+ and macOS or Linux, plus the CLI of the AI you use. Checking your Python version, fixing a mismatch and the per-OS install steps are in the [README](../README.md#requirements).

### Choosing Claude, GPT or Gemini

The first `hive` asks which AI runs the hive and remembers the answer in `~/.hive/state.json`:

```
🤖 Which AI should run the hive? (change it later with `hive provider`)
  ❯ 1) Claude  Claude Code
    2) GPT     Codex CLI  (not installed: npm install -g @openai/codex)
    3) Gemini  Gemini CLI
```

- `hive provider` shows the menu again, and `hive provider gpt` switches directly. Without a terminal, `hive provider` lists the providers and which are installed.
- `--provider gemini` uses another provider for one run, without changing the saved choice. `--queen gpt-5.4` picks its provider too.
- Each provider remembers its own last Queen and bee model. A Queen and her bees always come from one provider.
- Without a terminal and with nothing saved, the hive uses Claude.

| Provider | Runs in | Default Queen | Default bees |
|---|---|---|---|
| Claude | Claude Code | Opus 5.5 | Haiku 5.5 |
| GPT | Codex CLI | GPT-5.5 with an API key; with a ChatGPT plan, the plan's own Queen model (for example GPT-5.6-Terra) | GPT-6 Luna |
| Gemini | Gemini CLI | Gemini 3.1 Pro | Gemini 3.5 Flash-Lite |

### Setting up Claude

1. Install [Claude Code](https://code.claude.com), or use the hive's own copy: `.venv/bin/pip install -e ".[bundled]"`.
2. Sign in the way Claude Code does: your Claude Code login (subscription), or `ANTHROPIC_API_KEY`. With a subscription, report costs are the API-equivalent price of the same tokens; with an API key, they're real dollars.
3. `hive provider claude`, then `hive doctor`: it shows the Claude Code version, validates the plugin, re-reads the last session's transcript (the statistics depend on its format) and warns about environment variables that would override the bees' model.

### Setting up GPT (Codex CLI)

1. Install it: `npm install -g @openai/codex`.
2. Sign in: `codex login` with your ChatGPT plan, or set `OPENAI_API_KEY`. If Codex keeps your login in the system keychain rather than in `~/.codex/auth.json`, sign in once for the hive too: `CODEX_HOME=~/.hive/codex codex login`.
3. `hive provider gpt`, then `hive models --check`.
4. **Approve the hive's hooks once.** Codex runs hooks only after you approve them. Run this from any folder, approve the hive's hooks when Codex asks (or type `/hooks`), then quit:
   ```bash
   CODEX_HOME=~/.hive/codex codex
   ```
   Codex saves the approval in `~/.hive/codex/config.toml` and ties it to each hook's command line. The commands run copies of the hook scripts in `~/.hive/codex/hooks/`, refreshed on every run, so moving the hive or updating a script doesn't undo the approval; a change to `hooks.json` itself makes Codex ask again, and `hive doctor` then says so.
5. `hive doctor` should show `hooks: approved`.

Until the hooks are approved, a GPT run has **no protected-path guard, no read-only reviewers and no live log**: in a test, a GPT run wrote a protected `.env`, and once the hooks were approved the same write, and a patch to the same file, were blocked. `hive` warns on every GPT run until then.

**ChatGPT plan models.** A ChatGPT sign-in can't use the API models (GPT-5.5 …). The hive adds the models your plan lists (read from Codex's `models_cache.json`), uses Codex's own default as the Queen and GPT-6 Luna for the bees when the plan offers it. A plan isn't billed per token, so these models cost $0 in the report, and they're left out of the "alone" estimates, until you set prices for them (below).

### Setting up Gemini (Gemini CLI)

1. Install it: `npm install -g @google/gemini-cli`.
2. Create an API key in [Google AI Studio](https://aistudio.google.com/apikey) and export it where every shell finds it:
   ```bash
   echo 'export GEMINI_API_KEY="…"' >> ~/.zshrc     # bash: ~/.bashrc
   ```
   Google no longer serves the Gemini CLI to personal Google logins, so the key (or Vertex AI credentials) is needed. `~/.zprofile` alone isn't enough: only login shells read it, and some terminals and tools don't. With the key set, the hive's Gemini settings switch to API-key sign-in by themselves.
3. `hive provider gemini`, then `hive models --check`.
4. `hive doctor` warns if `GEMINI_API_KEY` isn't set.

### How the hive runs Codex and the Gemini CLI

The hive never edits your own `~/.codex` or `~/.gemini`. It keeps its own config home for each:

| | Codex | Gemini CLI |
|---|---|---|
| Home | `~/.hive/codex` (as `CODEX_HOME`) | `~/.hive/gemini` (as `GEMINI_CLI_HOME`); each session gets its own folder in `sessions/`, removed after two weeks |
| From your own home | `auth.json` and `config.toml`, linked if you have them | the login files (`oauth_creds.json`, `.env` …), linked; `settings.json`, copied with the hive's hooks added |
| The Queen's instructions | passed per session (`developer_instructions`) | the session folder's `GEMINI.md`, so sessions running at once don't mix |
| Bees | agent roles in `agents/*.toml` | sub-agents in `agents/*.md` |
| Session logs (for the report) | `sessions/…/rollout-*.jsonl` | `.gemini/tmp/<project>/chats/`, shared by all sessions |

The rules, bees, hooks and skills are generated there from the files in `hive/core` on every run, so a retro still edits `rules/queen.md` and `agents/<name>.md` there, and the change reaches all three providers. Codex and the Gemini CLI write only inside granted folders, so interactive sessions also grant `hive/core/rules/` and `hive/core/agents/` (not its hook scripts; headless runs, which have no retro, get neither). Only the Queen may write there: the protect hook denies bees, in Codex as in Claude Code. The Gemini CLI doesn't tell hooks which bee is calling, so there it rests on the bees' instructions.

**Bee settings** come from the frontmatter of `hive/core/agents/<name>.md`, as for the Haiku bees:

| Frontmatter | Codex | Gemini CLI |
|---|---|---|
| `effort: medium` | `model_reasoning_effort = "medium"` | thinking level MEDIUM, per sub-agent (`modelConfigs.customOverrides`) |
| `autoCompactWindow: 100000` | `model_auto_compact_token_limit = 100000` | (no per-bee setting) |
| (no turn or time limit) | | up to 100 turns and 30 minutes; the CLI's defaults, 30 turns and 10 minutes, cut builders off |

### What differs from Claude

| | Claude | GPT | Gemini |
|---|---|---|---|
| Cost in the report | exact, from Claude Code | tokens × list price ($0 on a ChatGPT plan) | tokens × list price |
| Protected paths | hook | hook, once approved | hook |
| Read-only scouts | hook | Codex's read-only sandbox | no write or shell tools |
| Read-only reviewers | hook | hook, once approved | instructions only: the CLI doesn't tell hooks which bee runs a tool |
| Live log | each bee when it starts and reports; commands with ✅/❌ | each bee when it reports (Codex has no hook for starting one); commands without ✅/❌, since Codex's hooks don't report the exit code (the saved report has it) | each bee when it starts and reports; commands with ✅/❌ |
| Network for commands | yes | in `plan` and `auto` mode (`sandbox_workspace_write.network_access`), so bees can install dependencies; off in `ask` mode and with `--sandbox` | yes |
| Bee names in the CLI | `queen-hive:scout` … | "Scout bee" … (Codex allows only ASCII in names) | "🔎 Scout bee" … |
| Brief IDs | from the brief | from the task name (`s1_count_lines` → S1): Codex keeps briefs encrypted | from the brief |
| Profile draft on first use | a Haiku scout reads the project | manifest files only, or the Queen with the `init` skill | manifest files only, or the Queen with the `init` skill |
| `--budget` cap, `--compare`, local bees | yes | no | no |

GPT and Gemini prices come from price trackers, not the providers' pages; each model's price has its own date (`hive models` shows the range). Set your own in `~/.hive/models.json`, for example for a ChatGPT plan model (the numbers are only an example):

```json
{"prices": {"gpt-5.6-terra": {"input": 2, "output": 12, "cache_read": 0.2}}}
```

GPT and Gemini have run against signed-in CLIs (Codex 0.171, Gemini CLI 0.65) on small jobs only, so expect rough edges.

### Check which models you can use

```bash
hive models --check                  # your provider: one tiny request per Queen and the default bees
hive models --check --provider gpt   # another provider
hive models --all                    # every provider's catalog
```
```
model        id                   in/out $/M   role       access
fable-5.1    claude-fable-5-1     10/50        queen      ✅
mythos-5.1   claude-mythos-5-1    10/50        queen      ✗ model_not_found
opus-5.5     claude-opus-5-5      4/20         queen      ✅
sonnet-5.5   claude-sonnet-5-5    2/10         queen      ✅
...
```

`hive doctor` shows the chosen provider and, for each installed CLI, its version and sign-in state (for Codex also whether the hooks are approved).

## 3. Your first run

```bash
hive                           # asks which folder to work on
# or
hive -d ~/projects/shop "Add a combo discount: coffee + croissant makes the croissant half price"
```

1. **The folder:** without `-d` or a folder in the goal, the hive asks which folder to work on. Pick a project it already knows by number, type a path, or press Enter for the current folder.
2. **First use of a folder:** the hive drafts the project's profile. With Claude, a Haiku scout reads the project for it; with GPT and Gemini the draft comes from manifest files only, and if you keep the empty template instead (**n**), the Queen drafts it with the `init` skill in your first session. Review it: **[Y]es** saves it, **[e]dit** opens it in `$EDITOR`, and **[n]o** keeps an empty template. Check **Commands** and **Protected paths** in particular. Folders called `acceptance/` are suggested as protected automatically.
3. **Confirm the settings:** `Run with Claude (Claude Code): 👑 Claude Opus 5.5 · 🐝 Claude Haiku 5.5 bees · 🛡 mode plan? [Y/n]`. These are your last choices for this provider, or its defaults on first use. Enter runs with them. **n** opens a menu for each: the Queen, the bee model and the mode (plan, auto or ask). Your answers become the new defaults.
4. **Your provider's CLI opens** (Claude Code, Codex or the Gemini CLI) with the hive loaded: the Queen's rules, the bees, the hooks and the skills. It's the CLI's normal interface, so everything you know from it works. If you gave a goal, the Queen starts on it straight away. Otherwise type one. You can give several goals in one session; each finished job ends with a `hive-summary` block, and then the Queen runs the **waggle**: what went wrong, with one proposed edit per item. Reply with the items to apply (for example `apply 1 and 3`). Nothing changes without your approval.
5. **Exit the CLI** (`/exit` or Ctrl-D in Claude Code, `/quit` in Codex and the Gemini CLI). The hive then runs the acceptance check for the last job and prints a report per job. Every job is saved as a run for `hive stats` and the dashboard.

**The report** after you exit (from a real run on a small Node shop):

```
variant                                       passed   tokens in/out   cache r/w       cost      time
🐝 Hive (Claude Opus 5.5 + Claude Haiku 5.5)   ✅        4.2k/63.7k      1.87M/173.5k    $1.00     3.9m
   └ queen                                             52/14.9k        1.19M/51.6k     ≈$0.949
   └ build                                             722/12.9k       90.7k/15.4k     ≈$0.009
   └ review                                            3.4k/36.0k      587.0k/106.4k   ≈$0.037
≈  Claude Sonnet 5.5 alone (estimate)                                                  $1.71
≈  Claude Opus 5.5 alone (estimate)                                                    $3.05
acceptance ✅ $ node --test acceptance/combo.spec.js
acceptance ✅ $ npm test
review: lenses goal, correctness, tests, arch, perf, rules, security · confirmed 0 · fixed 0 · dismissed 6 · open 0
🐝 Hive $1.00 vs Claude Opus 5.5 alone $3.05 (estimate, same tokens) → saved 67%
```

Read "saved" with care: an ≈ estimate reprices the hive's own tokens at another model's price, but a model working alone uses far fewer tokens. Measured side by side (`--compare`), single models did the [benchmark tasks](../README.md#benchmarks) for less (§8).

**Scripts and CI.** Without a terminal, or with `--headless`, the hive doesn't open the CLI's interface. It runs the goal in the CLI's print mode, prints the Queen's progress, stops at the end and prints the same report. A goal is required, there's no waggle, and with Claude `--budget` is a hard cap. A headless run's `--queen`, `--workers` and `--mode` apply to that run only: only interactive runs change the defaults `hive` offers you.

The hive never commits. Review the changes with `git diff` and commit them yourself.

## 4. Commands and flags

### `hive ["goal"]` (also `hive run`)

| Flag | Meaning |
|---|---|
| `-d, --dir DIR` | Grant access to a folder (repeatable). Folders named in the goal (`~/x`, `/abs`, `./x`, quoted paths) are granted automatically. The first folder is the working directory. With no folder at all, the hive asks in a terminal (Enter = the current folder) and uses the current folder in scripts. |
| `--queen KEY` | `fable-5.1`, `opus-5.5`, `sonnet-5.5` …, `gpt-5.5`, `gpt-5.6-terra` …, `gemini-3.1-pro` … (`hive models --all` lists them). It also picks the provider. Not asked about. |
| `--workers KEY` | Bee model: `haiku-5.5`, `gpt-6-luna` or `gemini-3.5-flash-lite` by default. Any model of the same provider works, e.g. `sonnet-5.5` for harder builds. Not asked about. |
| `--mode plan\|auto\|ask` | Autonomy mode. Not asked about. With `--queen`, `--workers` and `--mode` all given, nothing is asked. |
| `--review full\|light\|off` | `full` runs the lenses that fit the task, sized to the change; `light` runs only goal + tests; `off` skips the review (the Queen still verifies every brief). The default is the Queen's own: `full` for most Queens, `light` for Sonnet 5.5, where a full review cost more than Sonnet alone for no change in the results. |
| `--lenses a,b,c` | Exact lenses: `goal, correctness, tests, arch, perf, rules, security` for code, `facts, goal` for research, `goal, scope` for files. |
| `--done "CMD"` | Acceptance command that must pass (repeatable). The hive runs it itself after the job, and it decides ✅/❌. Without it, the hive runs the Queen's final checks plus the profile's `test` command. The Queen's checks need your approval in `ask` mode or with `--sandbox` (README → Safety). |
| `--compare [MODELS]` | Also redo the job with single models alone, in copies of the folder. The default is `sonnet-5.5,opus-4.8,opus-5.5`, and `all` means every available Queen. Asks for confirmation first (`--yes` skips that). |
| `--provider claude\|gpt\|gemini` | The AI for this run only (§2). |
| `--headless` | Run without the CLI's interface and stop at the end. This is the default when there's no terminal. |
| `--budget USD` | Hard cap for a headless Claude run, 5 by default. Each `--compare` model gets the same cap. Claude Code has no cap for interactive sessions, and Codex and the Gemini CLI have none at all. |
| `--scout/--builder/--reviewer MODEL` | A model for one kind of bee only, for example a local model (§11). |
| `--sandbox` | Run shell commands in the CLI's sandbox. In Claude Code: writes only inside the granted folders and temp, network only to allowed domains, so installs may need approval. The Gemini CLI gets its own `--sandbox`. Codex always sandboxes commands to the granted folders, and `--sandbox` also turns off its network. |
| `--no-init` | Don't draft a profile on first use. |
| `--no-waggle` | Don't have the Queen run the retro after each finished job. |

The exit code is 0 when the last job finished and acceptance passed (or there was no acceptance command), and 1 otherwise. This makes headless runs usable in scripts.

### Other commands

| Command | What it does |
|---|---|
| `hive review [TARGET]` | Opens your provider's CLI on an independent review of existing changes, without building anything: uncommitted changes by default, or a branch, a commit range, or a PR number. |
| `hive waggle` / `hive retro` | Opens your provider's CLI with a retro of the project's last run: what went wrong, plus proposed minimal edits to the rules or memory. Nothing changes until you approve an item. |
| `hive init [DIR] [--no-ai] [--force]` | Draft or redraft a project's profile. With Claude a Haiku scout reads the project; `--no-ai`, GPT and Gemini only read manifest files. |
| `hive models [--check] [--provider P \| --all]` | Catalog, prices and your access for your provider (or all of them), local models included. |
| `hive models add KEY MODEL_ID [--url URL]` / `hive models remove KEY` | Add or remove a local model (§11). |
| `hive stats [DIR] [--last]` | Run history: cost, pass rate and average saving. `--last` reprints the last full report. |
| `hive dashboard [up\|down\|status] [--port 7777] [--no-open] [--foreground]` | The web dashboard (§9). It runs as a background process; `hive dashboard down` stops it. |
| `hive doctor` | The provider, each CLI's version and sign-in (and Codex's hook approval), plugin validation, a transcript check and warnings. |
| `hive provider [NAME]` | Shows or changes which AI runs the hive: claude, gpt or gemini (§2). |
| `hive install-plugin` | Installs the plugin into Claude Code (§10). |

## 5. Choosing a Queen and a mode

**Queen.** The Queen's tokens are most of the bill (in the example above, $0.95 of $1.00), so match her to the job. For Claude:

| Queen | Use it for |
|---|---|
| **Opus 5.5** (default) | Most real work: features, refactors, tricky bugs, and large or vague work where planning and triage matter. |
| **Sonnet 5.5** | Everyday and well-defined work. In the benchmarks a Sonnet Queen with `--review light` got the same results as the defaults for about half the cost. Half Opus's price per token. |
| **Fable 5.1** | The hardest, longest or vaguest work. It costs 2.5× Opus 5.5 per token. |
| **Opus 4.8 / Opus 5** | Comparisons, or if you prefer their style. |

With GPT and Gemini the same idea holds: a strong Queen (GPT-5.5, or your ChatGPT plan's balanced model such as GPT-5.6-Terra; Gemini 3.1 Pro) for real work, and a faster one (Gemini 3.8 Flash) for small, clear tasks. `hive models --check` shows which ones your login can use.

**Mode:**

| Mode | Behavior | Use when |
|---|---|---|
| `plan` (default) | The Queen explores read-only, then shows her briefs and review lenses. You choose **[a]pprove**, **[e]dit** (type feedback, and she revises) or **[c]ancel**. After approval the hive works on its own. | Anything you care about. You see the plan before any change is made. |
| `auto` | No questions. Edits and commands run inside the granted folders. | Throwaway branches, well-tested repos, overnight jobs. |
| `ask` | Edits inside granted folders are automatic. Shell commands not listed in the profile's Commands, web access and any path outside the granted folders ask **y / n / always**. | Unfamiliar repos and sensitive machines. |

In every mode, edits outside the granted folders are refused (`ask` asks you instead), and protected paths can never be changed.

## 6. Writing good goals and Done-when checks

- **Say what "done" means.** The best goals come with a check: `--done "npm test"`, `--done "go test ./..."`, or a human-written acceptance test in a protected folder. This is the single most effective thing you can do.
- **Point at specs.** `"Do task 3 from docs/backlog.md"` works well when the spec lives in the repo.
- **Mention folders** right in the goal: `"Port the date helpers from ~/old-app to ~/new-app"` grants both.
- **One goal at a time.** Give the next one after the Queen's summary, in the same session.
- **Protect what the bees must not change.** Put acceptance tests in a folder and list it under *Protected paths* in the profile.
- **Write the language you think in.** The Queen answers in the language of the goal.

## 7. Any stack, any language, non-coding work

- **Stacks:** `hive init` detects package.json (npm/yarn/pnpm), pyproject/requirements, go.mod, Cargo.toml, pom.xml, Gradle, .csproj/.sln, Gemfile, composer.json, mix.exs, deno.json, pubspec.yaml, Package.swift, CMake and Makefile targets. Then a scout refines the commands by reading CI configs and READMEs. The Queen uses those commands in every Done when.
- **Human languages:** goals in Russian, English or any other language get answers in the same language. Code follows the project's conventions.
- **Research:** `hive "Compare the three auth libraries we use and recommend one" --review light`. Scouts read the code and the web, and the `facts` lens checks every claim has a source.
- **Files and automation:** `hive "Summarize every PDF in ~/reports/2026 into ~/reports/2026/summary.md"`. The `scope` lens checks nothing else was changed or deleted.

## 8. Reading the statistics

- **tokens in/out and cache r/w:** exact per-model totals from the CLI's session log (Claude Code's transcript, Codex's rollout, the Gemini CLI's chat log), split into stages: queen, scout, build, fix and review. Stage figures are scaled to the exact totals, and stage costs are marked ≈.
- **cost:** with Claude and an API key, the real charge; with a Claude subscription, the **API-equivalent** cost: what the same tokens would cost on the API. GPT and Gemini costs are tokens × list price, and $0 for ChatGPT plan models without a price you set (§2).
- **≈ Model alone (estimate):** the hive's own tokens repriced at that model's price. It's free and instant, but rough: a model working alone uses a different number of tokens.
- **⚖️ Model alone (`--compare`):** real runs. The folder is copied before the hive starts, as copy-on-write clones where the file system supports them (APFS, Btrfs, XFS), so even large folders copy in about a second. Links leading out of the copy are removed. Each model does the whole job alone, without subagents, with the same goal, budget, protected paths and acceptance commands. You get real tokens, cost, time and ✅/❌. The diffs are kept in the run folder (`compare-<model>.diff`) and the copies are deleted.
- **saved X%:** the hive against the Queen model alone, using the measured run if there is one, otherwise the estimate.

Be honest with yourself about the numbers, and compare like for like: the hive's Queen against the same model alone. In both [benchmarks](../README.md#benchmarks), nine tasks from small features to realistic issues scored on hidden tests, every variant solved every task. With an Opus 5.5 Queen the hive cost about 30% less than Opus 5.5 alone, because the Queen only coordinates (bees read and write, checks return a verdict, the review is sized to the change). With a Sonnet 5.5 Queen (light review by default) it got the same results as Sonnet 5.5 alone for about 25% more; on quick changes a single cheap model is still the cheaper tool.

All of this is saved in `~/.hive/projects/<p>/runs/<id>/run.json`, with an event log alongside it. `hive stats` summarizes it.

## 9. The dashboard

```bash
hive dashboard          # starts it in the background and opens http://localhost:7777
hive dashboard status   # is it running, and where
hive dashboard down     # stops it
```

The dashboard keeps running after you close the terminal, until `hive dashboard down`. Running `hive dashboard` again while it's up just reopens the browser. Its pid and port are in `~/.hive/dashboard.json` and its output goes to `~/.hive/dashboard.log`. To run it in the terminal instead (Ctrl-C stops it), use `hive dashboard --foreground`.

| Page | Shows |
|---|---|
| **Live** | The running session started by `hive` (headless runs too): the Queen's latest message, each brief as a card (status, return count, Done when, and the full brief and report), the review lenses, checks and cost. Updates in real time. |
| **Runs** | Every run across projects, filterable by project, Queen and result. Click one for its full timeline. |
| **Run page** | The bee tree, a comparison bar chart (hive vs ⚖️ measured and ≈ estimated models), tokens and cost by stage, acceptance results, review counts, timeline, and **Export as HTML**, a single offline file you can share. |
| **Compare** | Cost per run against "Queen alone" over time, and per-Queen averages (cost, pass rate, saving). |
| **Projects** | Each project's memory files (profile, progress, decisions, known issues). |
| **Models** | Each provider's catalog with prices (hover a price for its date), access and last Queen, and **Re-check access** for every installed CLI. |

It binds to localhost only, it's read-only, and it needs no internet.

## 10. The Claude Code plugin

The bees, the Queen's rules, the hooks and the skills (`waggle`, `review`, `init`) live in `hive/core`, which is laid out as a Claude Code plugin. The `hive` CLI loads it automatically. To use it inside Claude Code too:

```bash
hive install-plugin
# runs: claude plugin marketplace add ~/queen-hive/hive  &&  claude plugin install queen-hive@hive-local
```

Then, in any Claude Code session:

| Command | Effect |
|---|---|
| `/queen-hive:hive <goal>` | The current session becomes the Queen and follows the same rules and memory. The Queen model is your session's model (`/model` to change it). |
| `/queen-hive:review [target]` | An independent review of changes by reviewer bees, without building. |
| `/queen-hive:init` | Draft or refresh this project's hive profile. |
| `/queen-hive:waggle` or `/queen-hive:retro` | A retro of the current session. `/queen-hive:hive` runs it by itself when the job finishes, unless you ask it not to ("no waggle"). |

Inside Claude Code, permissions follow Claude Code's own settings, so there's no hive mode question. The protection hook is active there too.

To try it without installing: `claude --plugin-dir ~/queen-hive/hive/core`. Inside `hive` sessions an installed copy is switched off automatically, so nothing loads twice.

With GPT and Gemini there's nothing to install: `hive` generates the same rules, bees, hooks and skills from this plugin into its Codex and Gemini homes on every run (§2), and the skills are named without the prefix (`waggle`, `review`, `init`).

## 11. Customizing bees and rules

| To change | Edit |
|---|---|
| How the Queen works | `hive/core/rules/queen.md` |
| A bee's instructions, tools or effort | `hive/core/agents/<bee>.md`. Keep `model:` a full ID such as `claude-haiku-5-5`. |
| Bee model for one run | `--workers sonnet-5.5` for all bees, or `--scout`, `--builder`, `--reviewer` for one kind. The hive loads a copy of the plugin with those models swapped in. |
| Model prices or new models | `hive/models.py` (`CATALOG`, with each model's `priced_on` date), or your own prices in `~/.hive/models.json` (§2) |
| Project facts | `~/.hive/projects/<p>/profile.md`, or `hive init --force` |
| Retro, review, profile drafting | `hive/core/skills/<waggle\|review\|init>/SKILL.md` |

`hive waggle` proposes edits to exactly these files after a session, so let the hive tune itself and approve what makes sense.

### Local models

Bees can run on a model on your own machine, served by Ollama (0.14+), llama.cpp or LM Studio through their Claude-compatible API. Local tokens cost nothing.

```bash
ollama serve                                   # in another terminal
hive models add qwen-coder qwen2.5-coder:14b   # --url for a server other than http://localhost:11434
hive models --check                            # sends one tiny request to the local server
hive "Map the payment flow" --scout qwen-coder
```

Claude Code sends all requests to one address, so when a bee is local the hive starts a small router on localhost for the session. Claude requests pass through to Anthropic unchanged, with your login. Requests for the local model go to its server, without your login headers.

Things to know:
- Anthropic doesn't support non-Claude models in Claude Code, so this can break with a Claude Code update.
- Small models often fail at tool use. Use a coding model of 14B or more, with a large context window.
- Start with scouts, which are read-only. Keep reviewers on Claude, because the independent review is only worth as much as the reviewer.

## 12. Costs and safety

- **Budget:** in headless Claude runs, `--budget` (default $5) is a hard cap, and the run stops with `error_max_budget_usd` when it's reached. Interactive Claude Code sessions have no cap, and Codex and the Gemini CLI have none at all: watch the cost in the CLI and the report. `--compare` multiplies the worst case by the number of models, and the hive asks before starting.
- **Guards against runaway spending:** bees can't spawn bees in any of the three CLIs, and in Claude Code and Codex at most 5 run at once (the Gemini CLI has no such limit). In Claude Code the built-in subagents are disabled, and the Codex and Gemini Queens are told to use only the hive's bees, so every helper is a hive bee on the model you chose.
- **Containment:** the hive works only in the folders you grant, and Claude Code asks before edits anywhere else. In Claude Code and the Gemini CLI, shell commands aren't sandboxed by default, so in `auto` mode a command *can* reach outside the folders. Use `--sandbox` or `ask` mode on sensitive machines. Codex always sandboxes commands to the granted folders, with network in `plan` and `auto` mode only.
- **Read-only bees:** a hook denies every file edit by scouts and reviewers, and every shell write outside the temp folders. In Codex this needs the hooks approved (§2); in the Gemini CLI scouts get no write tools and reviewers are read-only by instruction.
- **Protected paths:** the hook blocks file tools and shell writes (`>`, `rm`, `mv`, `cp` to the path, `tee`, `sed -i`, `git checkout/restore` …) on protected paths. The shell check is a careful parse, not a sandbox.
- **Git:** work in a git repo. The hive never commits, and the start point of each run is recorded, so `git diff` shows exactly what it did.
- **The hive itself:** no bee may change its rules, bees, hooks or skills; the protect hook denies it (in the Gemini CLI, which doesn't name the calling bee, the bees' instructions say so). Only the Queen does, when she applies a retro item you approved. The exception is a project that contains the hive itself (working on the hive's own code): there its files are ordinary project files.
- **Data:** memory and run logs stay in `~/.hive`, which the hive keeps owner-only (permissions 700). The dashboard is local only: it answers only requests to `localhost` and POSTs from its own pages.
- **Memory changes:** the report after a session lists every line the Queen added to the project memory (📝). Those lines become part of her instructions next time.

## 13. Troubleshooting and FAQ

**"⚠️ the hive's bees were not loaded"**
Run `hive doctor`. The plugin must validate. Make sure no `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is set in your shell.

**A Queen shows ✗ in the menu**
Your login can't use that model. Run `hive models --check` to re-check, for example after a plan change.

**The Queen asked me something after 3 returns**
That's the designed stop. The brief kept failing. Read the error she shows, then clarify the goal or fix the environment (missing dependency, wrong test command in the profile).

**A reviewer flagged something wrong**
The Queen verifies every finding herself and dismisses false positives with a reason. You'll see the reason in the report and on the dashboard.

**"⚠️ Codex doesn't run the hive's hooks yet"**
Approve them once: `CODEX_HOME=~/.hive/codex codex`, then approve the hive's hooks (or type `/hooks`). `hive doctor` then shows `hooks: approved` (§2).

**A GPT model shows "not supported when using Codex with a ChatGPT account"**
That's an API model; a ChatGPT plan has its own. `hive models --check --provider gpt` lists the ones your plan offers, and the hive uses them by default.

**Gemini says "API key not valid" or asks for a login**
`GEMINI_API_KEY` isn't set in the shell that runs `hive`. Export it in `~/.zshrc` (or `~/.bashrc`), open a new terminal, and check with `hive doctor`.

**Plan mode in a script**
Plan and ask modes need a terminal. In scripts or CI, use `--mode auto`.

**Where is everything?**
- `~/.hive/state.json`: your provider, last Queen and bees per provider, mode, model access
- `~/.hive/projects/<folder>-<hash>/`: memory and `runs/`
- `~/.hive/codex`, `~/.hive/gemini`: the hive's Codex and Gemini homes (§2)
- `~/.hive/models.json`: your own prices and local models

Delete a project folder there to make the hive forget a project.

**Why is the hive more expensive than Sonnet alone on my tiny task?**
Planning, verifying and reviewing cost a fixed overhead. Use `--review light` or `off` and `--queen sonnet-5.5` for small jobs, and the full hive for real ones. `--compare` shows the truth for your own workload.
