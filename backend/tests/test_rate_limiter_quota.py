# -*- coding: utf-8 -*-
"""
Tests for the tiered rate limiter with per-agent guaranteed quota (ADR-004).

Covers:
- Global bucket normal behaviour
- Per-agent guaranteed quota bypass when global bucket is empty
- Multiple agents concurrent fairness
- Backward compatibility (agent_name=None)
- Snapshot includes per-agent stats
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.services.rate_limiter import LLMRateLimiter


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a fresh singleton."""
    LLMRateLimiter.reset_instance()
    yield
    LLMRateLimiter.reset_instance()


def _make_limiter(**kwargs) -> LLMRateLimiter:
    """Create a limiter with test-friendly defaults."""
    defaults = {
        "requests_per_minute": 60,
        "burst_capacity": 5,
        "enabled": True,
        "min_tokens_per_agent": 3,
        "agent_window_seconds": 60.0,
    }
    defaults.update(kwargs)
    return LLMRateLimiter(**defaults)


# ------------------------------------------------------------------
# Basic global bucket tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_bucket_basic_acquire():
    """Tokens can be acquired up to burst capacity."""
    limiter = _make_limiter(burst_capacity=3)
    results = [await limiter.acquire(timeout=0.1) for _ in range(3)]
    assert results == [True, True, True]
    # 4th should fail immediately (timeout=0)
    result = await limiter.acquire(timeout=0.0)
    assert result is False


@pytest.mark.asyncio
async def test_disabled_limiter_always_succeeds():
    """When disabled, acquire always returns True."""
    limiter = _make_limiter(enabled=False, burst_capacity=1)
    results = [await limiter.acquire(timeout=0.0) for _ in range(10)]
    assert all(results)


@pytest.mark.asyncio
async def test_agent_name_none_backward_compatible():
    """agent_name=None should work exactly like the old behaviour."""
    limiter = _make_limiter(burst_capacity=2)
    assert await limiter.acquire(timeout=0.1, agent_name=None) is True
    assert await limiter.acquire(timeout=0.1, agent_name=None) is True
    assert await limiter.acquire(timeout=0.0, agent_name=None) is False


# ------------------------------------------------------------------
# Per-agent guaranteed quota tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guaranteed_quota_bypasses_empty_global_bucket():
    """When global bucket is empty, agent with remaining quota still gets tokens."""
    limiter = _make_limiter(burst_capacity=2, min_tokens_per_agent=3)

    # Drain global bucket with agent_name=None (no quota tracking)
    assert await limiter.acquire(timeout=0.1, agent_name=None) is True
    assert await limiter.acquire(timeout=0.1, agent_name=None) is True
    # Global bucket is now empty

    # Agent "price" hasn't used any tokens yet → guaranteed quota kicks in
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True

    # price has now used 3 tokens (= min_tokens_per_agent), no more guarantee
    # AND global bucket is still empty → should fail
    assert await limiter.acquire(timeout=0.0, agent_name="price") is False

    stats = limiter.snapshot()
    assert stats["guaranteed_grants"] == 3


@pytest.mark.asyncio
async def test_multiple_agents_each_get_guaranteed_quota():
    """6 agents should each get their guaranteed minimum even when global is depleted."""
    limiter = _make_limiter(burst_capacity=2, min_tokens_per_agent=2)
    agents = ["price", "news", "fundamental", "technical", "macro", "deep_search"]

    # Drain global bucket
    await limiter.acquire(timeout=0.1, agent_name=None)
    await limiter.acquire(timeout=0.1, agent_name=None)

    # Each agent should still get 2 guaranteed tokens
    for agent in agents:
        assert await limiter.acquire(timeout=0.0, agent_name=agent) is True
        assert await limiter.acquire(timeout=0.0, agent_name=agent) is True

    # Each agent should now be at their limit
    for agent in agents:
        assert await limiter.acquire(timeout=0.0, agent_name=agent) is False

    stats = limiter.snapshot()
    assert stats["guaranteed_grants"] == 12  # 6 agents × 2 tokens
    assert len(stats["agent_stats"]) == 6
    for agent in agents:
        assert stats["agent_stats"][agent]["usage_in_window"] == 2
        assert stats["agent_stats"][agent]["guaranteed_remaining"] == 0


@pytest.mark.asyncio
async def test_global_bucket_preferred_over_guaranteed():
    """When global bucket has tokens, they are used first (no guaranteed grant counted)."""
    limiter = _make_limiter(burst_capacity=5, min_tokens_per_agent=3)

    # These should come from global bucket, not guaranteed
    assert await limiter.acquire(timeout=0.1, agent_name="price") is True
    assert await limiter.acquire(timeout=0.1, agent_name="price") is True

    stats = limiter.snapshot()
    assert stats["guaranteed_grants"] == 0  # All from global bucket
    assert stats["agent_stats"]["price"]["usage_in_window"] == 2


@pytest.mark.asyncio
async def test_guaranteed_quota_window_expiry(monkeypatch):
    """Guaranteed quota resets after the agent_window_seconds."""
    limiter = _make_limiter(
        burst_capacity=0,
        min_tokens_per_agent=2,
        agent_window_seconds=1.0,
        requests_per_minute=0,  # No refill → global stays empty
    )

    # Use up guaranteed quota
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True
    assert await limiter.acquire(timeout=0.0, agent_name="price") is False

    # Fast-forward time past window
    original_monotonic = time.monotonic

    def _shifted_time():
        return original_monotonic() + 2.0

    monkeypatch.setattr(time, "monotonic", _shifted_time)

    # Quota should be available again
    assert await limiter.acquire(timeout=0.0, agent_name="price") is True


# ------------------------------------------------------------------
# Snapshot tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_includes_agent_stats():
    """Snapshot should include per-agent usage and remaining quota."""
    limiter = _make_limiter(burst_capacity=10, min_tokens_per_agent=5)

    await limiter.acquire(timeout=0.1, agent_name="price")
    await limiter.acquire(timeout=0.1, agent_name="price")
    await limiter.acquire(timeout=0.1, agent_name="news")

    stats = limiter.snapshot()
    assert "agent_stats" in stats
    assert stats["agent_stats"]["price"]["usage_in_window"] == 2
    assert stats["agent_stats"]["price"]["guaranteed_remaining"] == 3
    assert stats["agent_stats"]["news"]["usage_in_window"] == 1
    assert stats["agent_stats"]["news"]["guaranteed_remaining"] == 4
    assert stats["min_tokens_per_agent"] == 5
    assert stats["total_requests"] == 3


# ------------------------------------------------------------------
# Convenience function tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_llm_token_passes_agent_name():
    """The global convenience function should pass agent_name through."""
    from backend.services.rate_limiter import acquire_llm_token

    LLMRateLimiter._instance = _make_limiter(burst_capacity=2)
    assert await acquire_llm_token(timeout=0.1, agent_name="macro") is True
    assert await acquire_llm_token(timeout=0.1, agent_name="macro") is True

    stats = LLMRateLimiter.get_instance().snapshot()
    assert stats["agent_stats"]["macro"]["usage_in_window"] == 2


@pytest.mark.asyncio
async def test_acquire_llm_token_backward_compat():
    """Calling without agent_name should still work (backward compat)."""
    from backend.services.rate_limiter import acquire_llm_token

    LLMRateLimiter._instance = _make_limiter(burst_capacity=1)
    assert await acquire_llm_token(timeout=0.1) is True
    assert await acquire_llm_token(timeout=0.0) is False
