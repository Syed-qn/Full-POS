# tests/ratelimit/test_bucket.py
import pytest

from app.ratelimit.bucket import TokenBucketLimiter


@pytest.fixture
async def limiter(redis_client):
    return TokenBucketLimiter(redis_client)


async def test_allows_up_to_capacity_then_blocks(limiter):
    key = "test:bucket:1"
    results = [
        await limiter.allow(key, capacity=3, refill_per_sec=0.0) for _ in range(5)
    ]
    assert all(r[0] for r in results[:3])
    assert results[3][0] is False  # 4th blocked
    assert results[3][1] > 0  # retry-after seconds


async def test_independent_keys(limiter):
    a = await limiter.allow("k:a", capacity=1, refill_per_sec=0.0)
    b = await limiter.allow("k:b", capacity=1, refill_per_sec=0.0)
    assert a[0] is True and b[0] is True
