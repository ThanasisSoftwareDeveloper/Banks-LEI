"""
Token-bucket rate limiter with per-host tracking.
Prevents request floods to GLEIF and lei-lookup.com.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class TokenBucket:
    """Token bucket for a single host."""
    rate: float          # tokens per second
    capacity: float      # max burst
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False)

    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait)
                self.tokens = 0
            else:
                self.tokens -= 1


class RateLimiterRegistry:
    """Registry of token buckets per API host."""

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}

    def register(self, host: str, rate: float, burst: float):
        self._buckets[host] = TokenBucket(rate=rate, capacity=burst)

    async def wait(self, host: str):
        if host in self._buckets:
            await self._buckets[host].acquire()


# Global registry
# GLEIF API: official, up to 2 req/s with burst 3
# lei-lookup.com: scraping, conservative 0.4 req/s (1 per 2.5s), burst 1
rate_limiter = RateLimiterRegistry()
rate_limiter.register("gleif", rate=2.0, burst=3.0)
rate_limiter.register("lei-lookup", rate=0.4, burst=1.0)
