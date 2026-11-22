import json
import subprocess
import sys

from hive import SCRIPTS_DIR, memory
from hivecore import matches, protecting_rule


def write_profile(root, protected, commands=""):
    pdir = memory.ensure_project(root)
    lines = "\n".join(f"- {p}" for p in protected)
    (pdir / "profile.md").write_text(f"# Project profile\n\n## Commands\n{commands}\n\n## Protected paths\n{lines}\n")
    return pdir


def test_project_dir_is_stable_and_outside_project(tmp_path, hive_home):
    root = tmp_path / "My Shop"
    root.mkdir()
    a, b = memory.project_dir(root), memory.project_dir(root / ".")
    assert a == b
    assert a.parent == hive_home / "projects"
    assert a.name.startswith("My-Shop-")
    pdir = memory.ensure_project(root)
    assert sorted(p.name for p in pdir.iterdir()) == sorted([*memory.MEMORY_FILES, "root.txt", "runs"])
    assert list(root.iterdir()) == []          # nothing written into the project
    assert memory.profile_is_blank(pdir)


def test_profile_parsing(tmp_path):
    pdir = write_profile(tmp_path, ["acceptance/", "`spec/contract.js`"], "- test: `npm test`\n- build:\n- lint: npm run lint")
    assert memory.protected_paths(pdir) == ["acceptance/", "spec/contract.js"]
    assert memory.commands(pdir) == {"test": "npm test", "lint": "npm run lint"}


def test_matches():
    assert matches("acceptance/promo.spec.js", "acceptance/")
    assert matches("acceptance", "acceptance/")
    assert not matches("acceptance-old/x.js", "acceptance/")
    assert matches("spec/a.js", "spec")
    assert matches("tests/data/x.json", "tests/*/x.json")
    assert not matches("src/app.js", "acceptance/")


def test_protecting_rule_walks_up_to_the_project(tmp_path):
    root = tmp_path / "proj"
    (root / "acceptance").mkdir(parents=True)
    write_profile(root, ["acceptance/"])
    assert protecting_rule(root / "acceptance" / "new.spec.js") == (root.resolve(), "acceptance/")
    assert protecting_rule(root / "src" / "x.js") is None
    assert protecting_rule(tmp_path / "elsewhere.txt") is None


def run_hook(payload, env):
    out = subprocess.run([sys.executable, str(SCRIPTS_DIR / "protect.py")], input=json.dumps(payload),
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "pass"


def test_protect_hook(tmp_path, hive_home):
    import os

    root = tmp_path / "proj"
    (root / "acceptance").mkdir(parents=True)
    write_profile(root, ["acceptance/"])
    env = {**os.environ, "HIVE_HOME": str(hive_home)}
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(root / "acceptance/a.spec.js")}, "cwd": str(root)}
    assert run_hook(edit, env) == "deny"
    relative = {"tool_name": "Write", "tool_input": {"file_path": "acceptance/b.js"}, "cwd": str(root)}
    assert run_hook(relative, env) == "deny"
    ok = {"tool_name": "Write", "tool_input": {"file_path": str(root / "src/a.js")}, "cwd": str(root)}
    assert run_hook(ok, env) == "pass"
    rm = {"tool_name": "Bash", "tool_input": {"command": "rm acceptance/a.spec.js"}, "cwd": str(root)}
    assert run_hook(rm, env) == "deny"
    read = {"tool_name": "Bash", "tool_input": {"command": "cat acceptance/a.spec.js"}, "cwd": str(root)}
    assert run_hook(read, env) == "pass"
    def bash(command):
        return run_hook({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}, env)

    # Reading and running protected files is fine, even with redirects elsewhere.
    assert bash("node --test acceptance/a.spec.js 2>&1 | tail -5") == "pass"
    assert bash("node --test acceptance/a.spec.js > /tmp/out.txt") == "pass"
    assert bash("cp acceptance/a.spec.js /tmp/copy.js && grep x acceptance/a.spec.js") == "pass"
    # Writing to them is not.
    assert bash("echo x > acceptance/a.spec.js") == "deny"
    assert bash("echo x >>acceptance/a.spec.js") == "deny"
    assert bash("cp /tmp/x.js acceptance/a.spec.js") == "deny"
    assert bash("sed -i '' 's/a/b/' acceptance/a.spec.js") == "deny"
    assert bash("git checkout -- acceptance/a.spec.js") == "deny"
    assert bash("npm test && mv acceptance/a.spec.js old.js") == "deny"
    assert bash("echo x | tee acceptance/new.js") == "deny"


def test_read_only_bees(tmp_path, hive_home):
    import subprocess
    import sys

    from hive import CORE_DIR

    def decide(agent_type, tool, tool_input):
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(tmp_path), "agent_type": agent_type}
        out = subprocess.run([sys.executable, str(CORE_DIR / "scripts" / "protect.py")], input=json.dumps(payload),
                             capture_output=True, text=True).stdout
        return "deny" if '"deny"' in out else "pass"

    assert decide("queen-hive:reviewer", "Edit", {"file_path": str(tmp_path / "a.py")}) == "deny"
    assert decide("queen-hive:scout", "Bash", {"command": "echo x > notes.md"}) == "deny"
    assert decide("queen-hive:reviewer", "Bash", {"command": "npm test > /tmp/out.txt 2>&1"}) == "pass"   # temp is fine
    assert decide("queen-hive:reviewer", "Bash", {"command": "git diff abc123"}) == "pass"
    assert decide("queen-hive:builder", "Edit", {"file_path": str(tmp_path / "a.py")}) == "pass"


def test_run_context(tmp_path, hive_home):
    context = memory.run_context(tmp_path)
    assert str(memory.project_dir(tmp_path)) in context and "retro-log.md" in context
    assert "queen-hive:init" in context                          # blank profile: draft it first


def test_lastrun_facts(tmp_path, hive_home):
    root = tmp_path / "shop"
    root.mkdir()
    run_dir = memory.ensure_project(root) / "runs" / "20261121-100000-abcd"
    run_dir.mkdir(parents=True)
    record = {"goal": "add combo", "status": "done", "queen": {"name": "Claude Opus 5.5"}, "workers": {"name": "Claude Haiku 5.5"},
              "hive": {"cost_usd": 1.0, "briefs": [{"label": "B1"}, {"label": "B1"}, {"label": "R-goal"}],
                       "checks": [{"command": "npm test", "ok": False}], "by_stage": {"queen": {"cost_usd_est": 0.9}}},
              "acceptance": {"results": [{"command": "npm test", "ok": True}]},
              "summary": {"review": {"lenses": ["goal"], "confirmed": 1, "open": ["rounding on refunds"]}}}
    (run_dir / "run.json").write_text(json.dumps(record))
    (run_dir / "events.jsonl").write_text(json.dumps({"kind": "report", "label": "B1", "ok": False, "text": "Result: failed"}) + "\n")
    out = subprocess.run([sys.executable, str(SCRIPTS_DIR / "lastrun.py"), str(root)], capture_output=True, text=True).stdout
    assert "returned: B1" in out and "failed checks by the Queen: npm test" in out
    assert "failed report from B1" in out and "open: rounding on refunds" in out
    empty = subprocess.run([sys.executable, str(SCRIPTS_DIR / "lastrun.py"), str(tmp_path)], capture_output=True, text=True).stdout
    assert "No recorded hive run" in empty


def test_memory_with_a_stray_byte_still_reads_and_protects(tmp_path):
    """Agents write memory with shell commands, which can leave a non-UTF-8 byte; that must not crash the report
    or switch off protected paths (the protect hook lets work through when it fails)."""
    from hive import memory

    pdir = memory.ensure_project(tmp_path)
    (pdir / "progress.md").write_bytes(b"# Progress\n- 2026 \x85 note\n")
    profile = (pdir / "profile.md").read_text().replace("## Protected paths\n", "## Protected paths\n- acceptance/\n")
    (pdir / "profile.md").write_bytes(profile.encode() + b"\n- note \x85\n")
    assert "note" in memory.read(pdir, "progress.md")
    assert memory.protected_paths(pdir) == ["acceptance/"]
