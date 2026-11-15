"""Hive state and per-project memory, all under ~/.hive (never inside the project)."""

import json
from pathlib import Path

import hive  # noqa: F401 - puts the plugin scripts on sys.path
from hivecore import (  # noqa: F401 - re-exported
    MEMORY_FILES,
    PROFILE_TEMPLATE,
    commands,
    ensure_project,
    hive_home,
    profile_is_blank,
    project_dir,
    protected_paths,
)


def state_path() -> Path:
    return hive_home() / "state.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(path)


def read(pdir: Path, name: str) -> str:
    path = pdir / name
    return path.read_text() if path.exists() else ""


def tail(pdir: Path, name: str, lines: int = 10) -> str:
    return "\n".join(read(pdir, name).splitlines()[-lines:])


def project_root(pdir: Path) -> Path | None:
    root = pdir / "root.txt"
    return Path(root.read_text().strip()) if root.exists() else None


def all_projects() -> list[Path]:
    base = hive_home() / "projects"
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []
