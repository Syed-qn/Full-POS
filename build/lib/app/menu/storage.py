# src/app/menu/storage.py
import hashlib
from pathlib import Path


class FileBlobStore:
    """Content-addressed blob store under <base_dir>/<restaurant_id>/<sha256>."""

    def __init__(self, base_dir: "Path | str"):
        self._base = Path(base_dir)

    def put(self, *, restaurant_id: int, data: bytes, content_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self._base / str(restaurant_id) / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return digest

    def get(self, *, restaurant_id: int, digest: str) -> "bytes | None":
        path = self._base / str(restaurant_id) / digest
        return path.read_bytes() if path.is_file() else None
