"""Change set of a folder since a snapshot, for folders that aren't git repos.

    python3 changes.py snapshot ROOT MANIFEST   # record sizes and mtimes
    python3 changes.py diff ROOT MANIFEST       # print added / modified / deleted files
"""

import json
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build", ".next", ".cache"}


def scan(root: Path) -> dict[str, list[float]]:
    files: dict[str, list[float]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            files[str(path.relative_to(root))] = [stat.st_size, stat.st_mtime]
    return files


def snapshot(root: Path, manifest: Path) -> None:
    manifest.write_text(json.dumps(scan(root)))


def diff(root: Path, manifest: Path) -> dict[str, list[str]]:
    before = json.loads(manifest.read_text())
    after = scan(root)
    return {
        "added": sorted(set(after) - set(before)),
        "modified": sorted(p for p in set(after) & set(before) if after[p] != before[p]),
        "deleted": sorted(set(before) - set(after)),
    }


if __name__ == "__main__":
    action, root, manifest = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if action == "snapshot":
        snapshot(root, manifest)
    else:
        for kind, paths in diff(root, manifest).items():
            for path in paths:
                print(f"{kind:9} {path}")
