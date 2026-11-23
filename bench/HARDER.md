# Harder benchmark: design

The first benchmark ([RESULTS.md](RESULTS.md)) answered "does the hive pass small, fully specified tasks?" Yes, and so
does every single model, more cheaply. It couldn't show what the hive is for, because:

- the acceptance tests were in the repo and named in `--done`, so every agent could aim straight at them;
- the tasks were small and fully specified, with nothing to plan and no traps for a review to catch;
- each variant ran once, so there's no measure of variance.

This benchmark asks the question that matters: **on realistic, underspecified work, does the hive ship fewer defects,
and at what cost per correct result?**

## Principles

1. **Hidden tests.** Each task has a hidden test suite that no agent sees or is told about. Agents get the task text, the
   repo and its visible tests only. The harness runs the hidden suite after the run.
2. **Partial credit.** The score is the share of hidden tests that pass, not pass/fail, plus a separate count of
   **regressions**: hidden tests of behaviour that worked before the task.
3. **Same conditions for every variant:** the same task text, repo, tools, a $8 cap and a 30-minute limit. Single models
   get the same "verify your work by running the tests" instruction the hive's Queen follows.
4. **Three trials per variant**, reported as mean and spread, so a lucky run can't decide a task.
5. **Fresh tasks,** written for this benchmark and not public before it runs, so no model has seen them.
6. **Calibrated difficulty.** A pilot drops tasks that every variant aces or every variant fails; neither tells the
   variants apart.

## Tasks

Mid-sized repos (2–5k lines, several modules, an existing but incomplete test suite), written like real issues, not specs.

| # | Task | What makes it hard | What a careful process should catch |
|---|---|---|---|
| 1 | **Multi-currency invoicing**: "customers in the EU need invoices in EUR" | Touches pricing, rounding, persistence and reports; the spec says nothing about rounding per line vs per total | Rounding drift between line items and totals; old invoices must still load |
| 2 | **Vague bug report**: "monthly totals are sometimes off by a day's revenue" | No failing test; the symptom is in reports, the cause is a timezone/DST boundary in the ingestion module | Fixing the symptom in reports (wrong) vs the cause; the DST edge in both directions |
| 3 | **Behaviour-preserving refactor**: split a 900-line module, remove duplicated parsing | Many callers; subtle differences between the duplicates are relied on | Regressions: the hidden suite is a large characterisation test of the old behaviour |
| 4 | **Security fix**: "uploads can escape the storage folder" | The obvious fix (`..` check) is incomplete | Hidden tests try encoded, absolute, symlink and Windows-style variants |
| 5 | **Schema migration with backfill**: add a required column to a SQLite store | Existing data, idempotent migration, rollback on failure | Running the migration twice; a partially failed backfill |
| 6 | **Performance under a budget**: a report takes 40 s on 200k rows, must take < 2 s with identical output | Easy to speed up while changing ordering or float formatting | Byte-identical output on hidden datasets, plus a time limit |
| 7 | **Concurrency bug**: a cache occasionally returns stale data under parallel requests | Hard to reproduce; the visible tests are single-threaded | Hidden stress test with many threads; no deadlock |
| 8 | **Non-Python stack**: a small TypeScript (Node) service needs rate limiting per API key | Tests the "any stack" claim; npm tests | Sliding window vs fixed window per the issue's wording; headers on 429 |

Each task has: `task.json` (the issue text, the visible test command), `repo/`, `hidden/` (tests plus anything they
need, copied in only for scoring) and `regression/` (hidden tests of behaviour that already worked).

## Variants

| Variant | Why |
|---|---|
| Hive: Opus 5.5 Queen, Haiku bees, full review | The product as designed |
| Hive light: Sonnet 5.5 Queen, Haiku bees, `--review light` | The cheap configuration the README recommends for smaller work |
| Opus 5.5 alone | The strongest single model |
| Sonnet 5.5 alone | The cheap single model |

GPT and Gemini hives can run the same tasks later as their own rows. Their single-model baselines need `--compare`
support outside Claude first.

## Measures

- **Hidden pass rate** (primary): share of hidden tests passing, averaged over trials.
- **Regressions:** failing `regression/` tests.
- **Cost per correct task:** total cost ÷ tasks with ≥ 95% hidden pass rate and no regressions.
- **Cost and time** per run, as now.
- **Review value** (hive only): defects the review confirmed and fixed, and whether those fixes changed the hidden pass rate.

## Harness changes (bench/run.py)

1. Stop passing the acceptance command as `--done`; pass only the visible test command, as a user would.
2. After each run, score every variant on a fresh copy of the starting repo: apply the variant's diff (the hive's
   working tree; for single models the `compare-<model>.diff` that `--compare` keeps), copy in `hidden/` and
   `regression/`, run them, and count passes per test.
3. Run the hive-light variant as its own hive run, not through `--compare`.
4. `--trials N`, and a 30-minute limit per run.
5. Results as mean ± spread per task and variant, and a summary table with the measures above.

## Cost

| Run | Size | Estimate |
|---|---|---|
| Pilot (calibrate difficulty, fix the harness) | 4 tasks × 4 variants × 1 trial | $15–30 |
| Full | 8 tasks × 4 variants × 3 trials (96 runs) | $120–200 |

The hive variants are most of it: about $2–5 per run on tasks this size, against $0.30–1.50 for single models.

## What would count as a win

The hive is worth its price if, on these tasks, it has a clearly **higher hidden pass rate or fewer regressions** than
Opus alone, enough that **cost per correct task** is comparable or better. If it doesn't, the README should say so, and
the hive's place is the cases where a missed defect costs more than the tokens.

## Pilot result (4 tasks, 1 trial)

Every variant, Sonnet 5.5 alone included, passed every hidden test with no regressions, on all four tasks
([HARD-RESULTS.md](HARD-RESULTS.md)). By the calibration rule above, all four tasks are too easy to tell the variants
apart, and the traps (daylight saving, symlinks, byte-identical floats, per-line rounding) were caught by every model.
The full run as designed would need much larger, longer tasks, for example real issues in real multi-thousand-line
codebases. Until then, the cheapest configuration with the same results here is a Sonnet 5.5 Queen with the light review; the defaults stay Opus 5.5 with the full review.

## After three rounds of a cheaper Queen

The same four tasks, re-run after the Queen was changed to coordinate only (see the README's benchmark section):
every variant still solved every task, and the hive with an Opus 5.5 Queen cost $1.03 against $1.37 for Opus 5.5
alone ([HARD-RESULTS.md](HARD-RESULTS.md)). The tasks are still too easy to show a difference in quality.
