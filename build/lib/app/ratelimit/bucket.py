# src/app/ratelimit/bucket.py
"""Async redis token-bucket limiter.

Tokens stored as a redis hash ``{tokens, ts}``; refill+consume is atomic via a
Lua script so concurrent callers cannot race the check-then-set.
"""
import time

# tokens stored as (count, last_refill_ts) in a redis hash; atomic refill+consume.
_LUA = """
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = cap; ts = now end
tokens = math.min(cap, tokens + (now - ts) * refill)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  if refill > 0 then retry = math.ceil((1 - tokens) / refill) else retry = ttl end
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return {allowed, retry}
"""


class TokenBucketLimiter:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._sha: str | None = None

    async def _script(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(_LUA)
        return self._sha

    async def allow(
        self, key: str, *, capacity: int, refill_per_sec: float, ttl: int = 3600
    ) -> tuple[bool, int]:
        sha = await self._script()
        now = time.time()
        res = await self._redis.evalsha(
            sha, 1, key, capacity, refill_per_sec, now, ttl
        )
        allowed, retry = int(res[0]), int(res[1])
        return (allowed == 1, retry)
