from __future__ import annotations

import json

from backend.api.stream_replay import ReplayBuffer


def test_replay_buffer_appends_monotonic_seq_and_replays_after_cursor():
    buffer = ReplayBuffer(max_events=8, max_runs=4, ttl_seconds=60)
    buffer.start_run("run-1")
    first = {"type": "token", "content": "A"}
    second = {"type": "done"}

    assert buffer.append("run-1", first) == 1
    assert buffer.append("run-1", second) == 2

    replay = buffer.replay_from("run-1", 1)
    assert replay is not None
    assert [seq for seq, _payload in replay] == [2]
    assert json.loads(replay[0][1]) == {"type": "done", "seq": 2}


def test_replay_buffer_keeps_only_latest_events_per_run():
    buffer = ReplayBuffer(max_events=2, max_runs=4, ttl_seconds=60)
    buffer.start_run("run-1")
    for value in ("A", "B", "C"):
        buffer.append("run-1", {"type": "token", "content": value})

    replay = buffer.replay_from("run-1", 0)
    assert replay is not None
    assert [json.loads(payload)["content"] for _seq, payload in replay] == ["B", "C"]


def test_replay_buffer_expires_inactive_run_by_ttl():
    now = [100.0]
    buffer = ReplayBuffer(max_events=8, max_runs=4, ttl_seconds=10, clock=lambda: now[0])
    buffer.start_run("run-expired")
    buffer.append("run-expired", {"type": "token", "content": "A"})

    now[0] = 111.0
    assert buffer.replay_from("run-expired", 0) is None


def test_replay_buffer_evicts_least_recently_used_run():
    buffer = ReplayBuffer(max_events=8, max_runs=2, ttl_seconds=60)
    buffer.start_run("run-1")
    buffer.start_run("run-2")
    assert buffer.replay_from("run-1", 0) == []

    buffer.start_run("run-3")

    assert buffer.replay_from("run-2", 0) is None
    assert buffer.replay_from("run-1", 0) == []
    assert buffer.replay_from("run-3", 0) == []
