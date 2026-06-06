# tests/menu/test_storage.py
from app.menu.storage import FileBlobStore


def test_put_get_roundtrip(tmp_path):
    store = FileBlobStore(base_dir=tmp_path)
    digest = store.put(restaurant_id=1, data=b"PDF-BYTES", content_type="application/pdf")
    assert digest  # sha256 hex
    assert store.get(restaurant_id=1, digest=digest) == b"PDF-BYTES"


def test_tenant_isolation(tmp_path):
    store = FileBlobStore(base_dir=tmp_path)
    digest = store.put(restaurant_id=1, data=b"X", content_type="image/png")
    assert store.get(restaurant_id=2, digest=digest) is None
