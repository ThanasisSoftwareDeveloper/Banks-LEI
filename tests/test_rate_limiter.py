"""Tests for the token-bucket rate limiter."""

import asyncio
import time

import pytest

from rate_limiter import RateLimiterRegistry, TokenBucket


class TestTokenBucket:
    def test_initial_tokens_equal_capacity(self):
        bucket = TokenBucket(rate=1.0, capacity=5.0)
        assert bucket.tokens == 5.0

    @pytest.mark.asyncio
    async def test_single_acquire_succeeds_immediately(self):
        bucket = TokenBucket(rate=10.0, capacity=10.0)
        t0 = time.perf_counter()
        await bucket.acquire()
        elapsed = time.perf_counter() - t0
        # Should be nearly instant (well under 100 ms)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_tokens_deplete_and_refill(self):
        """After draining the bucket, next acquire waits ~1/rate seconds."""
        rate = 10.0
        bucket = TokenBucket(rate=rate, capacity=1.0)
        # Drain the single token
        await bucket.acquire()
        # Next acquire should wait ~0.1 s (1/10 s)
        t0 = time.perf_counter()
        await bucket.acquire()
        elapsed = time.perf_counter() - t0
        assert elapsed >= 0.08, f"Expected wait ~0.1s, got {elapsed:.3f}s"
        assert elapsed < 0.5,   f"Wait too long: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_capacity_not_exceeded(self):
        bucket = TokenBucket(rate=1.0, capacity=3.0)
        # Wait long enough that more than capacity tokens would accumulate
        await asyncio.sleep(0.05)
        assert bucket.tokens <= 3.0


class TestRateLimiterRegistry:
    @pytest.mark.asyncio
    async def test_unknown_host_does_not_block(self):
        registry = RateLimiterRegistry()
        t0 = time.perf_counter()
        await registry.wait("unknown-host")
        assert time.perf_counter() - t0 < 0.05

    @pytest.mark.asyncio
    async def test_registered_host_is_throttled(self):
        registry = RateLimiterRegistry()
        registry.register("test-host", rate=5.0, burst=1.0)
        # Drain the burst token
        await registry.wait("test-host")
        # Second call should wait ~0.2 s (1/5)
        t0 = time.perf_counter()
        await registry.wait("test-host")
        elapsed = time.perf_counter() - t0
        assert elapsed >= 0.15
