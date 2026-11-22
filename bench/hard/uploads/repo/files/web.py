"""The upload endpoint: names arrive URL-encoded in the request path."""

from urllib.parse import unquote

from files.storage import Storage


def handle_upload(storage: Storage, raw_path: str, body: bytes) -> tuple[int, str]:
    """raw_path is what follows /upload/ in the URL. Returns (status, message)."""
    name = unquote(raw_path)
    if not name:
        return 400, "missing file name"
    try:
        storage.save(name, body)
    except ValueError as error:
        return 400, str(error)
    return 201, f"stored {name}"
