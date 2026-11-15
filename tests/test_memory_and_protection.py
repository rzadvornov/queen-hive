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
