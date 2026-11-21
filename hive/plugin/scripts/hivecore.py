"""Hive memory layout and protected-path rules.

Stdlib only: this file is shared by the `hive` Python app and by the plugin's
hook scripts, which run with whatever python3 Claude Code finds.
"""

import fnmatch
import hashlib
import os
import re
from pathlib import Path

MEMORY_FILES = ("profile.md", "progress.md", "decisions.md", "known-issues.md", "retro-log.md")

PROFILE_TEMPLATE = """# Project profile

## Stack
- (languages, frameworks, package manager)

## Folder map
- (folder or file: what it holds)

## Commands
- test:
- build:
- lint:
- run:

## Protected paths
<!-- Paths the hive must never change, relative to the project root. A trailing / means a whole folder. -->

## Notes
"""

def label_of(description: str, fallback: str = "#") -> str:
    """A brief's ID is the first word of its Agent description: S1, B2, R-arch, F1."""
    return description.split()[0] if description and description.split() else fallback


def stage_of(agent: str, label: str) -> str:
    """The hive stage of a bee, from its agent type and brief label (S1, B2, R-arch, F1)."""
    agent = agent.rsplit(":", 1)[-1]
    if agent == "reviewer" or label.startswith("R"):
        return "review"
    if label.startswith("F"):
        return "fix"
    if agent == "scout" or label.startswith("S"):
        return "scout"
    return "build"


TEMPLATES = {
    "profile.md": PROFILE_TEMPLATE,
    "progress.md": "# Progress\n\nEach line: date · what was done · how it was verified.\n",
    "decisions.md": "# Decisions\n\nEach line: the decision · the reason.\n",
    "known-issues.md": "# Known issues\n\nTraps worth remembering, so they aren't hit twice.\n",
    "retro-log.md": "# Retro log\n\nEach line: date · approved or rejected · the proposed edit, in a few words.\n",
}


def hive_home() -> Path:
    return Path(os.environ.get("HIVE_HOME") or Path.home() / ".hive").expanduser()


def project_dir(folder: str | Path) -> Path:
    """Memory folder for a target folder: ~/.hive/projects/<name>-<hash8>."""
    root = Path(folder).expanduser().resolve()
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", root.name or "root").strip("-") or "root"
    return hive_home() / "projects" / f"{name}-{digest}"


def ensure_project(folder: str | Path) -> Path:
    """Create the memory folder with empty templates; never overwrites existing files."""
    pdir = project_dir(folder)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "runs").mkdir(exist_ok=True)
    root_file = pdir / "root.txt"
    if not root_file.exists():
        root_file.write_text(str(Path(folder).expanduser().resolve()) + "\n")
    for name, text in TEMPLATES.items():
        path = pdir / name
        if not path.exists():
            path.write_text(text)
    return pdir


def profile_is_blank(pdir: Path) -> bool:
    path = pdir / "profile.md"
    return not path.exists() or path.read_text().strip() == PROFILE_TEMPLATE.strip()


def _section(text: str, title: str) -> list[str]:
    """Bullet lines ("- x") under a '## title' heading."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower() == title.lower()
            continue
        if inside and line.strip().startswith("- "):
            lines.append(line.strip()[2:].strip())
    return lines


def protected_paths(pdir: Path) -> list[str]:
    path = pdir / "profile.md"
    if not path.exists():
        return []
    return [p.strip("`") for p in _section(path.read_text(), "Protected paths") if p.strip("`")]


def commands(pdir: Path) -> dict[str, str]:
    """Commands from the profile, e.g. {"test": "npm test"}; empty values are skipped."""
    path = pdir / "profile.md"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for item in _section(path.read_text(), "Commands"):
        key, _, value = item.partition(":")
        value = value.strip().strip("`").strip()
        if key.strip() and value:
            result[key.strip().lower()] = value
    return result


def matches(rel: str, pattern: str) -> bool:
    """True if a project-relative path falls under a protected pattern."""
    rel = rel.replace(os.sep, "/").lstrip("./")
    pattern = pattern.replace(os.sep, "/").lstrip("./")
    if not pattern:
        return False
    if pattern.endswith("/"):
        return rel == pattern.rstrip("/") or rel.startswith(pattern)
    return rel == pattern or rel.startswith(pattern + "/") or fnmatch.fnmatch(rel, pattern)


def protecting_rule(target: str | Path) -> tuple[Path, str] | None:
    """If target is protected by any hive project that contains it, return (project root, pattern)."""
    path = Path(target).expanduser()
    path = path.resolve() if path.exists() else path.parent.resolve() / path.name
    for root in [path, *path.parents]:
        pdir = project_dir(root)
        if not pdir.exists():
            continue
        rel = os.path.relpath(path, root)
        for pattern in protected_paths(pdir):
            if matches(rel, pattern):
                return root, pattern
    return None


def read(pdir: Path, name: str) -> str:
    path = pdir / name
    return path.read_text() if path.exists() else ""


def tail(pdir: Path, name: str, lines: int = 10) -> str:
    return "\n".join(read(pdir, name).splitlines()[-lines:])


def run_context(root: str | Path) -> str:
    """What the Queen needs to know about a project's memory; shared by `hive` and the plugin command."""
    pdir = ensure_project(root)
    protected = protected_paths(pdir)
    return "\n".join([
        f"- Hive memory folder for this project: {pdir} ({', '.join(TEMPLATES)}). Write memory only there.",
        f"- Protected paths: {', '.join(protected)}" if protected else "- Protected paths: none listed",
        "- The profile is still an empty template: draft it first with the `haiku-hive:init` skill."
        if profile_is_blank(pdir) else "",
        "\n# Project profile\n" + read(pdir, "profile.md"),
        "\n# Known issues\n" + read(pdir, "known-issues.md"),
        "\n# Recent progress\n" + tail(pdir, "progress.md", 10),
    ])
