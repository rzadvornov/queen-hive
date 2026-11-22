"""Stores uploaded files under a root folder."""

from pathlib import Path


class Storage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        if ".." in name.split("/"):
            raise ValueError(f"invalid file name: {name}")
        return self.root / name

    def save(self, name: str, data: bytes) -> Path:
        path = self.path_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def read(self, name: str) -> bytes:
        return self.path_for(name).read_bytes()
