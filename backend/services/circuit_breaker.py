# -*- coding: utf-8 -*-
"""
Circuit breaker for upstream data sources.

States:
- CLOSED: normal operation.
- OPEN: short-circuits calls until the recovery timeout elapses.
- HALF_OPEN: allow a probe call; success closes the circuit, failure re-opens.
"""

from __future__ import annotations

import time
import os
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional, Any


CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


@dataclass
class _CircuitState:
    state: str = CLOSED
    failures: int = 0
    last_failure_ts: float = 0.0  # Unix timestamp
    opened_at_ts: float = 0.0     # Unix timestamp
    half_open_successes: int = 0


class CircuitBreaker:
    """
    Simple circuit breaker to guard unstable sources.

    Parameters:
        failure_threshold: consecutive failures before opening the circuit.
        recovery_timeout: seconds to wait before allowing a HALF_OPEN probe.
        half_open_success_threshold: number of successful probes required to close.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,
        half_open_success_threshold: int = 1,
        source_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(0.1, float(recovery_timeout))
        self.half_open_success_threshold = max(1, half_open_success_threshold)
        self._states: Dict[str, _CircuitState] = {}
        self._lock = RLock()
        self._source_overrides = source_overrides or {}

    # -----------------------------
    # Public API
    # -----------------------------
    def can_call(self, source: str) -> bool:
        """
        Whether the source is allowed to be called right now.
        Returns False when the circuit is OPEN and the cooldown has not elapsed.
        """
        with self._lock:
            state = self._states.get(source, _CircuitState())
            now = time.time()

            if state.state == OPEN:
                # Initialize opened_at if missing (defensive)
                if state.opened_at_ts == 0.0:
                    state.opened_at_ts = state.last_failure_ts or now

                elapsed = now - state.opened_at_ts
                recovery_timeout = self._get_recovery_timeout(source)
                if elapsed >= recovery_timeout:
                    # Transition to HALF_OPEN
                    state.state = HALF_OPEN
                    state.half_open_successes = 0
                    self._states[source] = state
                    return True
                return False

            # CLOSED or HALF_OPEN: allow the call
            self._states[source] = state
            return True

    def record_failure(self, source: str) -> None:
        """Increment failure count and open the circuit when threshold is reached."""
        with self._lock:
            state = self._states.get(source, _CircuitState())
            now = time.time()

            state.failures += 1
            state.last_failure_ts = now

            if state.state == HALF_OPEN:
                # Probe failed, re-open immediately
                state.state = OPEN
                state.opened_at_ts = now
                state.half_open_successes = 0
            elif state.failures >= self._get_failure_threshold(source):
                # Threshold reached, open circuit
                state.state = OPEN
                state.opened_at_ts = now

            self._states[source] = state

    def record_success(self, source: str) -> None:
        """
        Reset counters on success. In HALF_OPEN we wait for the configured number
        of probe successes before fully closing.
        """
        with self._lock:
            state = self._states.get(source, _CircuitState())

            if state.state == HALF_OPEN:
                state.half_open_successes += 1
                if state.half_open_successes >= self.half_open_success_threshold:
                    # Fully recovered
                    state = _CircuitState(state=CLOSED)
            else:
                # Normal success in CLOSED state, reset failures
                # (Optional: implementation choice to reset failures on any success)
                state.failures = 0
                state.last_failure_ts = 0.0
                state.opened_at_ts = 0.0

            self._states[source] = state

    def reset(self, source: Optional[str] = None) -> None:
        """Reset one source or all sources to CLOSED."""
        with self._lock:
            if source is None:
                self._states.clear()
            else:
                self._states[source] = _CircuitState()

    def get_state(self, source: str) -> Dict[str, Any]:
        """Return a snapshot of the circuit state for diagnostics."""
        with self._lock:
            state = self._states.get(source, _CircuitState())
            now = time.time()

            cooldown_remaining = 0.0
            recovery_timeout = self._get_recovery_timeout(source)
            if state.state == OPEN and state.opened_at_ts > 0:
                elapsed = now - state.opened_at_ts
                cooldown_remaining = max(0.0, recovery_timeout - elapsed)

            return {
                "state": state.state,
                "failures": state.failures,
                "last_failure_ts": state.last_failure_ts,
                "opened_at_ts": state.opened_at_ts,
                "half_open_successes": state.half_open_successes,
                "cooldown_remaining": round(cooldown_remaining, 2),
                "failure_threshold": self._get_failure_threshold(source),
                "recovery_timeout": recovery_timeout,
                "can_call": self._can_call_snapshot(state, now, source),
            }

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _can_call_snapshot(self, state: _CircuitState, now: float, source: str) -> bool:
        if state.state == OPEN:
            if state.opened_at_ts == 0.0:
                return False
            return (now - state.opened_at_ts) >= self._get_recovery_timeout(source)
        return True

    def _normalize_source(self, source: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in source.upper())

    def _get_override(self, source: str, key: str) -> Optional[Any]:
        override = self._source_overrides.get(source, {})
        if key in override:
            return override.get(key)
        return None

    def _get_failure_threshold(self, source: str) -> int:
        override = self._get_override(source, "failure_threshold")
        if override is not None:
            try:
                return max(1, int(override))
            except Exception:
                pass
        env_key = f"CB_{self._normalize_source(source)}_FAILURE_THRESHOLD"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return max(1, int(env_val))
            except Exception:
                pass
        return self.failure_threshold

    def _get_recovery_timeout(self, source: str) -> float:
        override = self._get_override(source, "recovery_timeout")
        if override is not None:
            try:
                return max(0.1, float(override))
            except Exception:
                pass
        env_key = f"CB_{self._normalize_source(source)}_RECOVERY_TIMEOUT"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return max(0.1, float(env_val))
            except Exception:
                pass
        return self.recovery_timeout
