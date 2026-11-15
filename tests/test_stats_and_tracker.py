from claude_agent_sdk import AssistantMessage, RateLimitEvent, RateLimitInfo, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage

from hive import models, pricing, stats, verify
from hive.pricing import Tokens
from hive.render import Tracker, stage_of


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
    t = Tracker(quiet=True)
    t.handle(msg([ToolUseBlock(id="a1", name="Agent", input={"description": "B1 x", "subagent_type": "haiku-hive:builder"})],
                 usage={"output_tokens": 10}))
    t.handle(msg([TextBlock(text="r")], model="claude-haiku-5-5", parent="a1", mid="h1", usage={"output_tokens": 1}))
    t.handle(msg([ToolUseBlock(id="a2", name="Agent", input={"description": "R-goal y", "subagent_type": "haiku-hive:reviewer"})],
                 mid="m2", usage={"output_tokens": 10}))
    t.handle(msg([TextBlock(text="r")], model="claude-haiku-5-5", parent="a2", mid="h2", usage={"output_tokens": 3}))
    exact = {"claude-haiku-5-5": Tokens(output=400), "claude-opus-5-5": Tokens(output=100)}
    stages = stats.stage_usage(t, exact)
    assert stages["build"]["tokens"]["output"] == 100 and stages["review"]["tokens"]["output"] == 300
    assert stages["queen"]["tokens"]["output"] == 100


def test_stage_of():
    assert stage_of("haiku-hive:reviewer", "R-arch") == "review"
    assert stage_of("haiku-hive:builder", "F1") == "fix"
    assert stage_of("haiku-hive:scout", "S1") == "scout"
    assert stage_of("haiku-hive:builder", "B2") == "build"


def msg(blocks, model="claude-opus-5-5", parent=None, mid="m1", usage=None):
    return AssistantMessage(content=blocks, model=model, parent_tool_use_id=parent, message_id=mid,
                            usage=usage or {"input_tokens": 100, "output_tokens": 10})


def test_tracker_stages_returns_and_dedupe():
    t = Tracker(quiet=True)
    t.handle(msg([ToolUseBlock(id="a1", name="Agent", input={"description": "B1 add promo", "subagent_type": "haiku-hive:builder"})]))
    t.handle(msg([TextBlock(text="working")], model="claude-haiku-5-5", parent="a1", mid="h1"))
    t.handle(msg([TextBlock(text="same message, split")], model="claude-haiku-5-5", parent="a1", mid="h1"))
    t.handle(UserMessage(content=[ToolResultBlock(tool_use_id="a1", content="Changed: x\nResult: failed", is_error=False)]))
    t.handle(msg([ToolUseBlock(id="a2", name="Agent", input={"description": "B1 retry", "subagent_type": "haiku-hive:builder"}),
                  ToolUseBlock(id="c1", name="Bash", input={"command": "npm test"})], mid="m2"))
    t.handle(UserMessage(content=[ToolResultBlock(tool_use_id="c1", content="fail", is_error=True)]))
    t.handle(RateLimitEvent(rate_limit_info=RateLimitInfo(status="allowed_warning", rate_limit_type="seven_day", utilization=0.8),
                            uuid="u", session_id="s"))
    assert t.returns == 1
    assert t.tokens_by_stage()["build"].input == 100          # duplicate usage counted once
    assert t.tokens_by_stage()["queen"].input == 200
    assert t.checks == [{"command": "npm test", "ok": False}]
    assert stats.weekly(t.rate_limits) == {"reported": True, "type": "seven_day", "now": 0.8, "delta": None, "resets_at": None}


def test_summary_and_acceptance_priority():
    text = 'Done!\n```hive-summary\n{"briefs": 2, "done_when": ["npm test", "<placeholder>"], "status": "done"}\n```'
    summary = verify.parse_summary(text)
    assert summary["briefs"] == 2 and verify.strip_summary(text) == "Done!"
    assert verify.acceptance_commands(["make check"], summary, {"test": "pytest"}) == ["make check"]
    assert verify.acceptance_commands([], summary, {"test": "pytest"}) == ["npm test"]
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
        "compare": [], "weekly": {"reported": False}, "summary": {"review": {"lenses": ["goal"], "confirmed": 1}},
        "path": str(tmp_path / "run.json"),
    }
    stats.print_report(record)
    out = capsys.readouterr().out
    assert "🐝 Hive" in out and "Claude Opus 5.5 alone (estimate)" in out and "acceptance ✅" in out and "saved" in out
