from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class _RunReplay:
    events: deque[tuple[int, str]]
    next_seq: int = 1
    completed: bool = False
    updated_at: float = 0.0


class ReplayBuffer:
    """保存近期 SSE 事件，支持按序号补发、TTL 与 run 级 LRU 淘汰。"""

    def __init__(
        self,
        *,
        max_events: int = 2048,
        max_runs: int = 64,
        ttl_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_events = max(1, int(max_events))
        self._max_runs = max(1, int(max_runs))
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._runs: OrderedDict[str, _RunReplay] = OrderedDict()
        self._lock = threading.RLock()

    def _prune_locked(self, now: float) -> None:
        if self._ttl_seconds > 0:
            expired = [
                run_id
                for run_id, entry in self._runs.items()
                if now - entry.updated_at > self._ttl_seconds
            ]
            for run_id in expired:
                self._runs.pop(run_id, None)
        while len(self._runs) > self._max_runs:
            self._runs.popitem(last=False)

    def start_run(self, run_id: str) -> None:
        normalized = str(run_id or "").strip()
        if not normalized:
            raise ValueError("run_id is required")
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            self._runs[normalized] = _RunReplay(
                events=deque(maxlen=self._max_events),
                updated_at=now,
            )
            self._runs.move_to_end(normalized)
            self._prune_locked(now)

    def append(self, run_id: str, event: dict[str, Any]) -> int:
        normalized = str(run_id or "").strip()
        if not normalized:
            raise ValueError("run_id is required")
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            entry = self._runs.get(normalized)
            if entry is None:
                entry = _RunReplay(events=deque(maxlen=self._max_events), updated_at=now)
                self._runs[normalized] = entry
            seq = entry.next_seq
            entry.next_seq += 1
            event["seq"] = seq
            payload = json.dumps(event, ensure_ascii=False, default=str)
            entry.events.append((seq, payload))
            entry.updated_at = now
            self._runs.move_to_end(normalized)
            self._prune_locked(now)
            return seq

    def replay_from(self, run_id: str, after_seq: int) -> list[tuple[int, str]] | None:
        normalized = str(run_id or "").strip()
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            entry = self._runs.get(normalized)
            if entry is None:
                return None
            entry.updated_at = now
            self._runs.move_to_end(normalized)
            return [(seq, payload) for seq, payload in entry.events if seq > after_seq]

    def mark_complete(self, run_id: str) -> None:
        normalized = str(run_id or "").strip()
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            entry = self._runs.get(normalized)
            if entry is None:
                return
            entry.completed = True
            entry.updated_at = now
            self._runs.move_to_end(normalized)

    def is_complete(self, run_id: str) -> bool | None:
        normalized = str(run_id or "").strip()
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            entry = self._runs.get(normalized)
            if entry is None:
                return None
            entry.updated_at = now
            self._runs.move_to_end(normalized)
            return entry.completed


replay_buffer = ReplayBuffer()
