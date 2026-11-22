from hive import models, pricing, stats, verify
from hive.pricing import Tokens
from hive.render import JobStats, format_event, stage_of


def test_tokens_from_both_usage_shapes():
    api = Tokens.from_usage({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7})
    cli = Tokens.from_usage({"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 100, "cacheCreationInputTokens": 7})
    assert api == cli and api.total == 122


def test_repricing():
    tokens = Tokens(input=1_000_000, output=1_000_000)
    assert pricing.cost(tokens, models.get("opus-5.5")) == 24.0
    assert pricing.cost(tokens, models.get("sonnet-5.5")) == 12.0
    assert pricing.cost_by_id(tokens, "claude-haiku-5-5[1m]") == 0.6
    assert models.get("claude-opus-4-8").key == "opus-4.8"


def test_cache_write_ttl_matches_reported_costs():
    # Real run: the Queen's session (1h cache) and the bees (5m cache) reproduce the CLI's costUSD.
    queen = Tokens(input=22, output=3686, cache_read=286644, cache_write=9473)
    bees = Tokens(input=1226, output=5783, cache_read=71007, cache_write=15260)
    assert abs(pricing.cost(queen, models.get("opus-5.5"), "1h") - 0.2069208) < 1e-6
    assert abs(pricing.cost(bees, models.get("haiku-5.5"), "5m") - 0.00563167) < 1e-6


def test_stages_scaled_to_exact_model_totals():
    t = JobStats()
    t.usage = {("queen", "claude-opus-5-5"): Tokens(output=20), ("build", "claude-haiku-5-5"): Tokens(output=1),
               ("review", "claude-haiku-5-5"): Tokens(output=3)}
    exact = {"claude-haiku-5-5": Tokens(output=400), "claude-opus-5-5": Tokens(output=100)}
    stages = stats.stage_usage(t, exact)
    assert stages["build"]["tokens"]["output"] == 100 and stages["review"]["tokens"]["output"] == 300
    assert stages["queen"]["tokens"]["output"] == 100


def test_stage_of():
    assert stage_of("queen-hive:reviewer", "R-arch") == "review"
    assert stage_of("queen-hive:builder", "F1") == "fix"
    assert stage_of("queen-hive:scout", "S1") == "scout"
    assert stage_of("queen-hive:builder", "B2") == "build"


def test_returns_count_repeated_build_and_fix_briefs():
    t = JobStats(label_counts={"B1": 3, "B2": 1, "F1": 2, "R-goal": 2})
    assert t.returns == 3                                     # B1 twice again, F1 once again; reviews don't count


def test_headless_event_lines():
    assert format_event({"kind": "dispatch", "stage": "build", "agent": "queen-hive:builder", "description": "B1 combo"}) \
        == "👑 → 🔨 builder   B1 combo"
    assert format_event({"kind": "check", "command": "npm test", "ok": False, "output": "x\n1 failed"}) == "👑 🔍 $ npm test\n   ❌ 1 failed"
    assert format_event({"kind": "report", "label": "B1", "ok": True, "text": "Changed: a.js\nResult: passed"}) == "   🐝 B1 📨 Changed: a.js"
    assert format_event({"kind": "queen_text", "text": "Done.\n```hive-summary\n{}\n```"}) == "👑 Done."
    assert format_event({"kind": "run_start"}) is None


def test_summary_and_acceptance_priority():
    text = 'Done!\n```hive-summary\n{"done_when": ["npm test", "<placeholder>", "pytest"], "status": "done"}\n```'
    summary = verify.parse_summary(text)
    assert summary["status"] == "done" and verify.strip_summary(text) == "Done!"
    assert verify.acceptance_commands(["make check"], summary, {"test": "pytest"}) == ["make check"]
    assert verify.acceptance_commands([], summary, {"test": "pytest"}) == ["npm test", "pytest"]   # profile test always, once
    assert verify.acceptance_commands([], None, {"test": "pytest"}) == ["pytest"]
    assert verify.parse_summary("no block") is None


def test_run_checks(tmp_path):
    results = verify.run_checks(["true", "echo hi && false"], tmp_path)
    assert [r["ok"] for r in results] == [True, False] and "hi" in results[1]["tail"]
    assert verify.passed(results) is False and verify.passed([]) is None


def test_report_prints(capsys, tmp_path):
    record = {
        "queen": {"key": "opus-5.5", "name": "Claude Opus 5.5"}, "workers": {"name": "Claude Haiku 5.5"},
        "hive": {"tokens": Tokens(1000, 200, 5000, 300).to_dict(), "cost_usd": 0.05, "duration_ms": 65000,
                 "by_stage": {"queen": {"tokens": Tokens(800, 100).to_dict(), "cost_usd_est": 0.04}}},
        "acceptance": {"commands": ["npm test"], "results": [{"command": "npm test", "ok": True}], "passed": True},
        "estimates": stats.estimates(Tokens(1000, 200, 5000, 300).to_dict(), ["opus-5.5", "sonnet-5.5"]),
        "compare": [], "summary": {"review": {"lenses": ["goal"], "confirmed": 1}},
        "path": str(tmp_path / "run.json"),
    }
    stats.print_report(record)
    out = capsys.readouterr().out
    assert "🐝 Hive" in out and "Claude Opus 5.5 alone (estimate)" in out and "acceptance ✅" in out and "saved" in out
    assert "weekly" not in out
