"""运行与实际请求分层限额；跨进程共享 SQLite 租约，不伪称内存锁是全站额度。"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

class CapacityExceeded(RuntimeError):
    pass


class LeaseLimiter:
    def __init__(self, path: str | Path | None = None):
        root = Path(__file__).resolve().parents[2]
        self.path = Path(path or os.getenv("FINSIGHT_RUNTIME_QUOTA_DB", str(root / "data/runtime_quota.sqlite")))

    def acquire(self, bucket: str, owner: str, maximum: int, *, owner_max: int | None = None,
                ttl: float = 360) -> str | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=3) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS runtime_leases (id TEXT PRIMARY KEY, bucket TEXT, owner TEXT, expires REAL)")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM runtime_leases WHERE expires <= ?", (time.time(),))
            count = conn.execute("SELECT COUNT(*) FROM runtime_leases WHERE bucket=?", (bucket,)).fetchone()[0]
            owned = conn.execute("SELECT COUNT(*) FROM runtime_leases WHERE bucket=? AND owner=?", (bucket, owner)).fetchone()[0]
            if count >= maximum or (owner_max is not None and owned >= owner_max):
                return None
            lease = uuid.uuid4().hex
            conn.execute("INSERT INTO runtime_leases VALUES (?,?,?,?)", (lease, bucket, owner, time.time() + ttl))
            return lease

    def release(self, lease: str) -> None:
        if not self.path.exists():
            return
        with sqlite3.connect(self.path, timeout=3) as conn:
            conn.execute("DELETE FROM runtime_leases WHERE id=?", (lease,))

    def reserve_window(self, bucket: str, amount: int, *, maximum: int,
                       requests: int, window: float = 60) -> str | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=3) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS runtime_windows (id TEXT PRIMARY KEY, bucket TEXT, amount INTEGER, expires REAL)")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM runtime_windows WHERE expires<=?", (time.time(),))
            count, total = conn.execute("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM runtime_windows WHERE bucket=?",
                                        (bucket,)).fetchone()
            if count >= requests or total + amount > maximum:
                return None
            identity = uuid.uuid4().hex
            conn.execute("INSERT INTO runtime_windows VALUES (?,?,?,?)", (identity, bucket, amount, time.time() + window))
            return identity

    def settle_window(self, identity: str, actual: int | None) -> None:
        if actual is None:
            return  # 缺usage时保守保留完整预占。
        with sqlite3.connect(self.path, timeout=3) as conn:
            conn.execute("UPDATE runtime_windows SET amount=? WHERE id=?", (max(0, actual), identity))

    def cancel_window(self, identity: str) -> None:
        with sqlite3.connect(self.path, timeout=3) as conn:
            conn.execute("DELETE FROM runtime_windows WHERE id=?", (identity,))

    @asynccontextmanager
    async def slot(self, bucket: str, owner: str, maximum: int, *, timeout: float = 15,
                   ttl: float = 360, owner_max: int | None = None):
        deadline = time.monotonic() + timeout
        lease = None
        while lease is None:
            lease = await asyncio.to_thread(self.acquire, bucket, owner, maximum, owner_max=owner_max, ttl=ttl)
            if lease is not None:
                break
            if time.monotonic() >= deadline:
                raise CapacityExceeded(bucket + "_capacity_exhausted")
            await asyncio.sleep(.1)
        try:
            yield
        finally:
            await asyncio.to_thread(self.release, lease)


class TokenReservations:
    """同一运行的并发预占；所有子 Agent 共享。"""
    def __init__(self, maximum: int = 160000):
        self.maximum = maximum
        self.spent = 0
        self.reserved = 0
        self._lock = asyncio.Lock()

    async def reserve(self, count: int) -> int:
        async with self._lock:
            if self.spent + self.reserved + count > self.maximum:
                raise CapacityExceeded("run_token_budget_exhausted")
            self.reserved += count
        return count

    async def settle(self, reservation: int, actual: int | None) -> None:
        async with self._lock:
            self.reserved -= reservation
            self.spent += reservation if actual is None else actual

