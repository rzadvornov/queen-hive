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

## Quick start

```bash
git clone <this repo> ~/the-hive && cd ~/the-hive
python3 -m venv .venv && .venv/bin/pip install -e .
ln -s ~/the-hive/.venv/bin/hive /usr/local/bin/hive   # or add .venv/bin to PATH

hive models --check          # which Queens your login can use
hive "Explain how this project is structured" -d ~/some/project
hive dashboard               # live view, history, comparisons
```

The Hive signs in with your Claude Code login or `ANTHROPIC_API_KEY`.

## What you get

- **Choose your Queen:** Fable 5.1, Opus 5.5, Sonnet 5.5, Opus 4.8 and others. Bees are Haiku 5.5.
- **Three ways to run it:** a one-shot CLI, `hive chat`, and the `/haiku-hive:hive` Claude Code plugin.
- **Autonomy modes:** `plan` (you approve the briefs), `auto`, or `ask` (risky actions need a y/n).
- **Briefs with "Done when":** every brief comes with a runnable check. The Queen re-runs each check herself and returns a brief at most 3 times before asking you.
- **Independent review:** Haiku reviewers check the finished work from separate lenses (goal, correctness, tests, architecture, performance, rules, security). They don't see the builders' reports.
- **Protected paths:** for example your acceptance tests. A hook blocks any edit to them.
- **Memory outside your project:** kept in `~/.hive/projects/…`. `hive waggle` (alias `retro`) proposes rule fixes after a session.
- **Statistics:** tokens and cost per stage, and weekly-limit usage. Each job is compared with single models, either estimated or, with `--compare`, as real side-by-side runs.

📖 **Full guide: [docs/GUIDE.md](docs/GUIDE.md)**
