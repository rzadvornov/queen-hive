"""Folders a goal talks about, and the run's starting point for review and rollback."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hive import SCRIPTS_DIR
import changes  # plugin script, on sys.path via the hive package

# Path-looking tokens: ~/x, /x, ./x, ../x, optionally quoted.
_PATH_RE = re.compile(r"""(?:"([^"]+)"|'([^']+)'|((?:~|\.{1,2})?/[^\s,;:"'`)]*))""")


def folders_in(goal: str) -> list[Path]:
    """Existing directories mentioned in the goal (a file counts as its folder), in order, no duplicates."""
    found: list[Path] = []
    for match in _PATH_RE.finditer(goal):
        raw = next(g for g in match.groups() if g)
        path = Path(raw.rstrip(".")).expanduser()
        if not path.exists():
            continue
        folder = (path if path.is_dir() else path.parent).resolve()
        if folder not in found:
            found.append(folder)
    return found


def resolve(goal: str, extra: list[Path], default: Path) -> list[Path]:
    folders: list[Path] = []
    for folder in [d.expanduser().resolve() for d in extra] + folders_in(goal):
        if not folder.is_dir():
            raise SystemExit(f"hive: not a folder: {folder}")
        if folder not in folders:
            folders.append(folder)
    return folders or [default.resolve()]


def git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def is_git(root: Path) -> bool:
    return git(root, "rev-parse", "--is-inside-work-tree") == "true"


@dataclass
class StartPoint:
    """How reviewers (and the user) can see what this run changed."""

    root: Path
    commit: str | None = None       # git: a commit holding the starting tree
    manifest: Path | None = None    # no git: file snapshot

    def instructions(self) -> str:
        if self.commit:
            return (
                f"The project is a git repo. The start point of this run is commit `{self.commit}` "
                f"(it includes uncommitted changes that existed before the run). Reviewers see the change set with "
                f"`git diff {self.commit}` plus new untracked files from `git status --short`."
            )
        return (
            "The project is not a git repo. Reviewers see the change set with "
            f"`python3 \"{SCRIPTS_DIR / 'changes.py'}\" diff \"{self.root}\" \"{self.manifest}\"` "
            "(it lists added, modified and deleted files)."
        )

    def to_dict(self) -> dict:
        return {"root": str(self.root), "commit": self.commit, "manifest": str(self.manifest) if self.manifest else None}


def start_point(root: Path, run_dir: Path) -> StartPoint:
    if is_git(root):
        # `git stash create` records the dirty tree as a commit without touching anything.
        commit = git(root, "stash", "create") or git(root, "rev-parse", "HEAD")
        if commit:
            return StartPoint(root, commit=commit)
    manifest = run_dir / "start-manifest.json"
    changes.snapshot(root, manifest)
    return StartPoint(root, manifest=manifest)
