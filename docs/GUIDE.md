# The Hive: user guide

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
| **👑 Queen** | The model you choose (Fable 5.1, Opus 5.5, Sonnet 5.5, …). It plans, writes briefs, checks results, runs the review and talks to you. It doesn't write code itself, except one- or two-line fixes. |
| **🐝 Bees** | Haiku 5.5 workers. **scout** researches (read-only), **builder** makes changes, and **reviewer** checks finished work (it never edits). |
| **Brief** | A task for one bee, at most 10 lines: *Goal / Read / Don't touch / Done when*. Each brief has an ID: `S1` (scout), `B2` (build), `R-arch` (review lens) or `F1` (fix after review). |
| **Done when** | A runnable command plus the output it must show, such as `npm test shows 0 failures`. |
| **Don't trust reports** | The Queen runs every Done-when check herself before accepting a brief. A failing brief goes back to a builder with the error output. **After 3 returns of the same brief she stops and asks you.** |
| **Independent review** | After the work is accepted, several reviewer bees check it in parallel, one *lens* each. They see only the goal, the change set and the project memory, **not** the builders' reports. The Queen triages every finding: false positives are dismissed with a reason, real defects get fix briefs, and opinions come to you as suggestions. At most 2 review rounds. |
| **Protected paths** | Files the hive must never change, typically your acceptance tests. A hook blocks every edit to them; reading and running them is fine. |
| **Project memory** | `~/.hive/projects/<folder>-<hash>/`: `profile.md` (stack, commands, protected paths), `progress.md`, `decisions.md`, `known-issues.md` and `runs/`. **Nothing is written into your project.** |
| **Waggle** | A retro after a job (alias `retro`). It runs automatically when a job finishes, proposes small edits to rules or memory based on what went wrong, and applies only the ones you approve. |

What a run looks like:

```
you ──goal──▶ 👑 Queen ──briefs──▶ 🐝 builders/scouts ──reports──▶ 👑 re-runs each Done when
                                                                         │
                       you ◀──summary + stats── 👑 triage ◀── 🐝 reviewers (in parallel, one lens each)
```

## 2. Install and sign in

Requirements: Python 3.10+ and macOS or Linux. Claude Code is optional; the SDK ships its own copy of the CLI. Checking your Python version, fixing a mismatch and the per-OS install steps are in the [README](../README.md#requirements).

**Sign in** works the same way as Claude Code: your existing Claude Code login (subscription) or `ANTHROPIC_API_KEY`.
- With a subscription, costs are the API-equivalent price of the same tokens.
- With an API key, they are real dollars.

Check which Queens you can use:

```bash
hive models --check      # one tiny request per model, a fraction of a cent
```
```
model        id                   in/out $/M   role       access
fable-5.1    claude-fable-5-1     10/50        queen      ✅
mythos-5.1   claude-mythos-5-1    10/50        queen      ✗ model_not_found
opus-5.5     claude-opus-5-5      4/20         queen      ✅
sonnet-5.5   claude-sonnet-5-5    2/10         queen      ✅
...
```

`hive doctor` shows versions, validates the plugin and warns about environment variables that would override the bees' model.

## 3. Your first run

```bash
hive                           # asks which folder to work on
# or
hive -d ~/projects/shop "Add a combo discount: coffee + croissant makes the croissant half price"
```

1. **The folder:** without `-d` or a folder in the goal, the hive asks which folder to work on. Pick a project it already knows by number, type a path, or press Enter for the current folder.
2. **First use of a folder:** a Haiku scout reads the project and drafts its profile. Review it: **[Y]es** saves it, **[e]dit** opens it in `$EDITOR`, and **[n]o** keeps an empty template. Check **Commands** and **Protected paths** in particular. Folders called `acceptance/` are suggested as protected automatically.
3. **Confirm the settings:** `Run with 👑 Claude Opus 5.5 · 🐝 Claude Haiku 5.5 bees · 🛡 mode plan? [Y/n]`. These are your last choices, or the defaults on first use. Enter runs with them. **n** opens a menu for each: the Queen, the bee model and the mode (plan, auto or ask). Your answers become the new defaults.
4. **Claude Code opens** with the hive loaded: the Queen's rules, the bees and the protection hook. It's the normal Claude Code interface, so everything you know from `claude` works. If you gave a goal, the Queen starts on it straight away. Otherwise type one. You can give several goals in one session; each finished job ends with a `hive-summary` block, and then the Queen runs the **waggle**: what went wrong, with one proposed edit per item. Reply with the items to apply (for example `apply 1 and 3`). Nothing changes without your approval.
5. **Exit Claude Code** (`/exit` or Ctrl-D). The hive then runs the acceptance check for the last job and prints a report per job. Every job is saved as a run for `hive stats` and the dashboard.

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

**Scripts and CI.** Without a terminal, or with `--headless`, the hive doesn't open Claude Code. It runs the goal on its own, prints the Queen's progress, stops at the end and prints the same report. A goal is required, there's no waggle, and `--budget` is a hard cap.

The hive never commits. Review the changes with `git diff` and commit them yourself.

## 4. Commands and flags

### `hive ["goal"]` (also `hive run`)

| Flag | Meaning |
|---|---|
| `-d, --dir DIR` | Grant access to a folder (repeatable). Folders named in the goal (`~/x`, `/abs`, `./x`, quoted paths) are granted automatically. The first folder is the working directory. With no folder at all, the hive asks in a terminal (Enter = the current folder) and uses the current folder in scripts. |
| `--queen KEY` | `fable-5.1`, `opus-5.5`, `sonnet-5.5`, `opus-5`, `opus-4.8`, … Not asked about. |
| `--workers KEY` | Bee model, `haiku-5.5` by default. Any catalog model works, e.g. `sonnet-5.5` for harder builds. Not asked about. |
| `--mode plan\|auto\|ask` | Autonomy mode. Not asked about. With `--queen`, `--workers` and `--mode` all given, nothing is asked. |
| `--review full\|light\|off` | `full` (default) runs every lens that fits the task, `light` runs only goal + tests, and `off` skips the review (the Queen still verifies every brief). |
| `--lenses a,b,c` | Exact lenses: `goal, correctness, tests, arch, perf, rules, security` for code, `facts, goal` for research, `goal, scope` for files. |
| `--done "CMD"` | Acceptance command that must pass (repeatable). The hive runs it itself after the job, and it decides ✅/❌. |
| `--compare [MODELS]` | Also redo the job with single models alone, in copies of the folder. The default is `sonnet-5.5,opus-4.8,opus-5.5`, and `all` means every available Queen. Asks for confirmation first (`--yes` skips that). |
| `--headless` | Run without Claude Code's interface and stop at the end. This is the default when there's no terminal. |
| `--budget USD` | Hard cap for a headless run, 5 by default. Each `--compare` model gets the same cap. Claude Code has no cap for interactive sessions. |
| `-v` | Headless: show every bee message and tool call. |
| `--no-init` | Don't draft a profile on first use. |
| `--no-waggle` | Don't have the Queen run the retro after each finished job. |

The exit code is 0 when the last job finished and acceptance passed (or there was no acceptance command), and 1 otherwise. This makes headless runs usable in scripts.

### Other commands

| Command | What it does |
|---|---|
| `hive waggle` / `hive retro` | Opens Claude Code with a retro of the project's last run: what went wrong, plus proposed minimal edits to the rules or memory. Nothing changes until you approve an item. |
| `hive init [DIR] [--no-ai] [--force]` | Draft or redraft a project's profile. `--no-ai` only reads manifest files. |
| `hive models [--check]` | Catalog, prices and your access. |
| `hive stats [DIR] [--last]` | Run history: cost, pass rate and average saving. `--last` reprints the last full report. |
| `hive dashboard [up\|down\|status] [--port 7777] [--no-open] [--foreground]` | The web dashboard (§9). It runs as a background process; `hive dashboard down` stops it. |
| `hive doctor` | Versions, plugin validation and warnings. |
| `hive install-plugin` | Installs the plugin into Claude Code (§10). |

## 5. Choosing a Queen and a mode

**Queen.** The Queen's tokens are most of the bill (in the example above, $0.95 of $1.00), so match her to the job:

| Queen | Use it for |
|---|---|
| **Fable 5.1** | The hardest, longest or vaguest work. It costs 2.5× Opus 5.5 per token. |
| **Opus 5.5** (default) | Most real work: features, refactors, tricky bugs. |
| **Sonnet 5.5** | Small, well-defined tasks where planning is easy. Half the price of Opus 5.5. |
| **Opus 4.8 / Opus 5** | Comparisons, or if you prefer their style. |

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

- **tokens in/out and cache r/w:** exact per-model totals from Claude Code, split into stages: queen, scout, build, fix and review. Stage figures are scaled to the exact totals, and stage costs are marked ≈.
- **cost:** with an API key, the real charge. With a subscription, the **API-equivalent** cost: what the same tokens would cost on the API.
- **≈ Model alone (estimate):** the hive's own tokens repriced at that model's price. It's free and instant, but rough: a model working alone uses a different number of tokens.
- **⚖️ Model alone (`--compare`):** real runs. The folder is copied before the hive starts. Each model does the whole job alone, without subagents, with the same goal, budget, protected paths and acceptance commands. You get real tokens, cost, time and ✅/❌. The diffs are kept in the run folder (`compare-<model>.diff`) and the copies are deleted.
- **saved X%:** the hive against the Queen model alone, using the measured run if there is one, otherwise the estimate.

Be honest with yourself about the numbers. On tiny tasks the hive's overhead (planning, verification, review) can cost **more** than one model alone. One real example: adding a `power()` function cost $0.19 with the hive and $0.10 with Sonnet alone. The hive pays off on real features, where its parallel cheap bees and independent review replace expensive single-model work.

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
| **Models** | Catalog, prices, access, and **Re-check access**. |

It binds to localhost only, it's read-only, and it needs no internet.

## 10. The Claude Code plugin

The bees, the Queen's rules, the protection hook and the waggle skill live in a Claude Code plugin (`hive/plugin`). The `hive` CLI loads it automatically. To use it inside Claude Code too:

```bash
hive install-plugin
# runs: claude plugin marketplace add ~/the-hive/hive  &&  claude plugin install haiku-hive@hive-local
```

Then, in any Claude Code session:

| Command | Effect |
|---|---|
| `/haiku-hive:hive <goal>` | The current session becomes the Queen and follows the same rules and memory. The Queen model is your session's model (`/model` to change it). |
| `/haiku-hive:waggle` or `/haiku-hive:retro` | A retro of the current session. `/haiku-hive:hive` runs it by itself when the job finishes, unless you ask it not to ("no waggle"). |

Inside Claude Code, permissions follow Claude Code's own settings, so there's no hive mode question. The protection hook is active there too.

To try it without installing: `claude --plugin-dir ~/the-hive/hive/plugin`.

## 11. Customizing bees and rules

| To change | Edit |
|---|---|
| How the Queen works | `hive/plugin/rules/queen.md` |
| A bee's instructions, tools or effort | `hive/plugin/agents/<bee>.md`. Keep `model:` a full ID such as `claude-haiku-5-5`. |
| Bee model for one run | `--workers sonnet-5.5`. The hive loads a copy of the plugin with that model swapped in. |
| Model prices or new models | `hive/models.py` (`CATALOG`, `PRICES_AS_OF`) |
| Project facts | `~/.hive/projects/<p>/profile.md`, or `hive init --force` |
| Retro behavior | `hive/plugin/skills/waggle/SKILL.md` |

`hive waggle` proposes edits to exactly these files after a session, so let the hive tune itself and approve what makes sense.

## 12. Costs and safety

- **Budget:** in headless runs, `--budget` (default $5) is a hard cap, and the run stops with `error_max_budget_usd` when it's reached. Interactive Claude Code sessions have no cap: watch the cost in Claude Code and the report. `--compare` multiplies the worst case by the number of models, and the hive asks before starting.
- **Guards against runaway spending:** bees can't spawn bees, at most 5 run at once, and Claude Code's built-in subagents are disabled, so every helper is a hive bee on the model you chose.
- **Containment:** the hive works only in the folders you grant. Shell commands are not sandboxed, though. In `auto` mode a command *can* reach outside the folders. Use `ask` mode on sensitive machines.
- **Protected paths:** the hook blocks file tools and shell writes (`>`, `rm`, `mv`, `cp` to the path, `tee`, `sed -i`, `git checkout/restore` …) on protected paths. The shell check is a careful parse, not a sandbox.
- **Git:** work in a git repo. The hive never commits, and the start point of each run is recorded, so `git diff` shows exactly what it did.
- **Data:** memory and run logs stay in `~/.hive`. The dashboard is local only.

## 13. Troubleshooting and FAQ

**"⚠️ the hive's bees were not loaded"**
Run `hive doctor`. The plugin must validate. Make sure no `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is set in your shell.

**A Queen shows ✗ in the menu**
Your login can't use that model. Run `hive models --check` to re-check, for example after a plan change.

**The Queen asked me something after 3 returns**
That's the designed stop. The brief kept failing. Read the error she shows, then clarify the goal or fix the environment (missing dependency, wrong test command in the profile).

**A reviewer flagged something wrong**
The Queen verifies every finding herself and dismisses false positives with a reason. You'll see the reason in the report and on the dashboard.

**Plan mode in a script**
Plan and ask modes need a terminal. In scripts or CI, use `--mode auto`.

**Where is everything?**
- `~/.hive/state.json`: last Queen and mode, model access
- `~/.hive/projects/<folder>-<hash>/`: memory and `runs/`

Delete a project folder there to make the hive forget a project.

**Why is the hive more expensive than Sonnet alone on my tiny task?**
Planning, verifying and reviewing cost a fixed overhead. Use `--review light` or `off` and `--queen sonnet-5.5` for small jobs, and the full hive for real ones. `--compare` shows the truth for your own workload.
