"""`hive init`: detect a folder's stack and draft its profile in the hive memory."""

import asyncio
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from hive import PLUGIN_DIR, memory, models, ui
from hive.folders import is_git

# manifest file → (stack label, {command: value})
_SIMPLE = {
    "go.mod": ("Go", {"test": "go test ./...", "build": "go build ./...", "lint": "go vet ./..."}),
    "Cargo.toml": ("Rust (cargo)", {"test": "cargo test", "build": "cargo build", "lint": "cargo clippy"}),
    "pyproject.toml": ("Python", {"test": "pytest"}),
    "requirements.txt": ("Python", {"test": "pytest"}),
    "setup.py": ("Python", {"test": "pytest"}),
    "pom.xml": ("Java (Maven)", {"test": "mvn test", "build": "mvn package"}),
    "build.gradle": ("JVM (Gradle)", {"test": "./gradlew test", "build": "./gradlew build"}),
    "build.gradle.kts": ("JVM (Gradle, Kotlin DSL)", {"test": "./gradlew test", "build": "./gradlew build"}),
    "Gemfile": ("Ruby", {"test": "bundle exec rake test"}),
    "composer.json": ("PHP (Composer)", {"test": "vendor/bin/phpunit"}),
    "mix.exs": ("Elixir", {"test": "mix test", "build": "mix compile"}),
    "deno.json": ("Deno", {"test": "deno test", "lint": "deno lint"}),
    "pubspec.yaml": ("Dart/Flutter", {"test": "dart test"}),
    "Package.swift": ("Swift", {"test": "swift test", "build": "swift build"}),
    "CMakeLists.txt": ("C/C++ (CMake)", {"build": "cmake -B build && cmake --build build"}),
}
_PROTECT_HINTS = ("acceptance", "acceptance-tests", "spec/acceptance", "tests/acceptance")


def detect(root: Path) -> dict:
    """Best-effort stack detection from manifest files. No API calls."""
    stacks: list[str] = []
    cmds: dict[str, str] = {}
    manifests: list[str] = []

    pkg = root / "package.json"
    if pkg.exists():
        manifests.append("package.json")
        runner = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        stacks.append(f"JavaScript/TypeScript ({runner})")
        try:
            scripts = json.loads(pkg.read_text()).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        for name in ("test", "build", "lint"):
            if name in scripts:
                cmds.setdefault(name, f"{runner} test" if name == "test" else f"{runner} run {name}")
        if "start" in scripts or "dev" in scripts:
            cmds.setdefault("run", f"{runner} start" if "start" in scripts else f"{runner} run dev")

    for name, (stack, defaults) in _SIMPLE.items():
        if (root / name).exists():
            manifests.append(name)
            if stack not in stacks:
                stacks.append(stack)
            for key, value in defaults.items():
                cmds.setdefault(key, value)

    for pattern, stack, defaults in (("*.csproj", ".NET", {"test": "dotnet test", "build": "dotnet build"}),
                                     ("*.sln", ".NET", {"test": "dotnet test", "build": "dotnet build"})):
        found = sorted(root.glob(pattern))
        if found:
            manifests.append(found[0].name)
            if stack not in stacks:
                stacks.append(stack)
            for key, value in defaults.items():
                cmds.setdefault(key, value)

    makefile = root / "Makefile"
    if makefile.exists():
        manifests.append("Makefile")
        targets = set(re.findall(r"^([A-Za-z0-9_.-]+):", makefile.read_text(errors="ignore"), re.M))
        for key in ("test", "build", "lint", "run"):
            if key in targets:
                cmds.setdefault(key, f"make {key}")

    protected = [f"{hint}/" for hint in _PROTECT_HINTS if (root / hint).is_dir()]
    return {"stacks": stacks, "commands": cmds, "manifests": manifests, "protected": protected, "git": is_git(root)}


def heuristic_profile(root: Path, found: dict) -> str:
    top = sorted(p.name + ("/" if p.is_dir() else "") for p in root.iterdir() if not p.name.startswith("."))[:25]
    stack = "\n".join(f"- {s}" for s in found["stacks"]) or "- (not detected; describe it here)"
    cmds = "\n".join(f"- {k}: `{found['commands'].get(k, '')}`" if found["commands"].get(k) else f"- {k}:"
                     for k in ("test", "build", "lint", "run"))
    folder_map = "\n".join(f"- {name}" for name in top) or "- (empty folder)"
    protected = "\n".join(f"- {p}" for p in found["protected"])
    return (
        f"# Project profile\n\n## Stack\n{stack}\n\n## Folder map\n{folder_map}\n\n## Commands\n{cmds}\n\n"
        "## Protected paths\n<!-- Paths the hive must never change, relative to the project root. "
        f"A trailing / means a whole folder. -->\n{protected}\n\n## Notes\n"
    )


def profile_rules() -> str:
    """The profile rules from the plugin's init skill: one source for `hive init` and the plugin."""
    text = (PLUGIN_DIR / "skills" / "init" / "SKILL.md").read_text()
    return text[text.index("## Profile rules"):].strip()


async def ai_profile(root: Path, draft: str) -> str | None:
    """Let a Haiku scout refine the heuristic draft by actually reading the project."""
    from hive import claude

    prompt = (f"Project folder: {root}\n\nHere is an automatic draft of the project profile, as the template:\n\n"
              f"{draft}\n\n{profile_rules()}\n\nReturn only the Markdown profile, nothing else.")
    args = ["--model", models.get(models.DEFAULT_WORKERS).id, "--tools", "Read", "Glob", "Grep",
            "--allowedTools", "Read", "Glob", "Grep", "--max-budget-usd", "0.50", "--setting-sources", ""]
    result = await asyncio.to_thread(claude.print_mode, args, prompt, root, None, 600)
    if result.get("is_error"):
        print(f"   (scout could not draft the profile: {str(result.get('result') or result.get('subtype'))[:200]})")
        return None
    text = result.get("result")
    if not text:
        return None
    fenced = re.search(r"```(?:markdown|md)?\n(.*?)```", text, re.S)
    text = (fenced.group(1) if fenced else text).strip()
    return text + "\n" if text.startswith("# ") else None


def _edit(text: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as handle:
        handle.write(text)
        path = handle.name
    subprocess.run([*editor.split(), path], check=False)
    return Path(path).read_text()


async def run(root: Path, use_ai: bool = True, force: bool = False) -> Path:
    """Create or refresh the profile for root. Returns the memory folder."""
    root = root.expanduser().resolve()
    pdir = memory.ensure_project(root)
    if not force and not memory.profile_is_blank(pdir):
        return pdir

    print(f"🐝 New project for the hive: {root}")
    found = detect(root)
    if found["manifests"]:
        print(f"   detected: {', '.join(found['stacks']) or 'unknown'} (from {', '.join(found['manifests'])})")
    if not found["git"]:
        print("   ⚠️  not a git repo: review still works from a file snapshot, but you have no easy rollback. "
              "Consider `git init` first.")

    draft = heuristic_profile(root, found)
    if use_ai:
        print("   a Haiku scout is reading the project to draft its profile…")
        draft = await ai_profile(root, draft) or draft

    print("\n" + draft)
    if ui.interactive():
        while True:
            answer = input("Save this profile? [Y]es / [e]dit / [n]o (keep the empty template): ").strip().lower()
            if answer in ("", "y", "yes"):
                break
            if answer in ("e", "edit"):
                draft = _edit(draft)
                print("\n" + draft)
                continue
            if answer in ("n", "no"):
                print(f"   kept the template. Edit it later: {pdir / 'profile.md'}")
                return pdir
    (pdir / "profile.md").write_text(draft)
    print(f"   saved: {pdir / 'profile.md'}")
    return pdir
