import pytest

from app.dispatch.preview_cache import (
    get_cached_preview,
    invalidate_preview_cache,
    set_cached_preview,
)


@pytest.mark.asyncio
async def test_preview_cache_roundtrip_and_invalidate():
    rid = 42
    await invalidate_preview_cache(rid)
    assert await get_cached_preview(rid) is None

    await set_cached_preview(rid, {1: "A", 2: "A"})
    hit = await get_cached_preview(rid)
    assert hit == {1: "A", 2: "A"}

    await invalidate_preview_cache(rid)
    assert await get_cached_preview(rid) is None