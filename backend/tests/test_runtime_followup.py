"""普通追问复用资料的时效、会话隔离与旧快照兼容边界。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.agent_runtime import data as data_module
from backend.agent_runtime.data import RunData


TTL_SECONDS = 12 * 3600


@pytest.fixture
def run_data(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=1_800_000_000.0)
    monkeypatch.setattr(data_module, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))

    def make(run_id, *, owner="alice", session_id="public:alice:thread"):
        return RunData(owner, session_id, run_id, "继续分析此前资料")

    return make, clock


def record_price(data, price):
    return data.record("fixture_quote", {"ticker": "AAPL"}, {
        "rows": [{"close": price}], "currency": "USD", "source": "测试报价",
        "url": f"https://example.com/quotes/{price}",
    })


def test_followup_saves_do_not_extend_inherited_record_expiry(run_data):
    make, clock = run_data
    parent = make("parent")
    ref = record_price(parent, 42)
    parent.save()
    original_expiry = clock.now + TTL_SECONDS

    for index in range(1, 4):
        clock.now += 3600
        child = make(f"child-{index}")
        assert child.restore(parent.run_id)
        assert child.rows(ref) == parent.rows(ref)
        child.save()
        parent = child

    clock.now = original_expiry + 1
    assert make("after-expiry").restore(parent.run_id) is False


def test_previous_chart_coverage_is_retained_for_verification_without_republishing(run_data):
    from backend.agent_runtime.analysis import render_chart
    make, clock = run_data
    parent = make('chart-parent')
    ref = parent.record('run_analysis_code', {}, {
        'rows': [{'date': '2026-11-05', 'ma20': None}, {'date': '2026-11-06', 'ma20': 42}]})
    chart = render_chart(parent, ref, '20日均线', 'line', 'date', [{'field': 'ma20'}])
    parent.save()
    child = make('chart-child')
    assert child.restore(parent.run_id)
    assert child.artifacts == []
    assert child.prior_artifacts[0]['coverage'] == chart['coverage']
    assert 'data' not in child.prior_artifacts[0]
    assert not make('foreign', owner='bob').restore(parent.run_id)
    clock.now += TTL_SECONDS + 1
    assert not make('expired').restore(parent.run_id)


def test_followup_keeps_fresh_records_after_inherited_records_expire(run_data):
    make, clock = run_data
    parent = make("parent")
    old_ref = record_price(parent, 42)
    old_sources = set(parent.source_refs(old_ref))
    parent.save()

    clock.now += TTL_SECONDS - 3600
    child = make("child")
    assert child.restore("parent")
    fresh_ref = record_price(child, 43)
    fresh_sources = child.source_refs(fresh_ref)
    child.save()

    clock.now += 3601
    followup = make("followup")
    assert followup.restore("child")
    assert set(followup.records) == {fresh_ref}
    assert followup.rows(fresh_ref)[0]["close"] == 43
    assert followup.source_refs(fresh_ref) == fresh_sources
    assert followup.source_refs(old_ref) == []
    assert not old_sources.intersection(followup.sources)
    assert all(source["data_ref"] == fresh_ref for source in followup.sources.values())
    with pytest.raises(ValueError, match="dataset_not_found_in_this_run"):
        followup.read(old_ref)


@pytest.mark.parametrize("seconds_elapsed", [TTL_SECONDS, TTL_SECONDS + 1])
def test_followup_rejects_records_at_or_after_expiry(run_data, seconds_elapsed):
    make, clock = run_data
    parent = make("parent")
    record_price(parent, 42)
    parent.save()

    clock.now += seconds_elapsed
    followup = make("followup")
    assert followup.restore("parent") is False
    assert followup.records == {}
    assert followup.sources == {}


@pytest.mark.parametrize(("owner", "session_id"), [
    ("alice", "public:alice:other-thread"),
    ("bob", "public:bob:thread"),
])
def test_followup_rejects_other_owner_or_session_even_if_snapshot_is_copied(run_data, owner, session_id):
    make, _clock = run_data
    parent = make("parent")
    record_price(parent, 42)
    parent.save()
    foreign = make("foreign", owner=owner, session_id=session_id)
    assert foreign.restore("parent") is False

    # 即使快照出现在错误作用域目录，也必须以文件中的身份校验拒绝恢复。
    destination = foreign._path("parent")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(parent._path("parent").read_text(encoding="utf-8"), encoding="utf-8")
    assert foreign.restore("parent") is False
    assert foreign.records == {}
    assert foreign.sources == {}


def test_followup_rejects_snapshot_with_different_run_identity(run_data):
    make, _clock = run_data
    parent = make("parent")
    record_price(parent, 42)
    parent.save()
    wrong_path = parent._path("different-run")
    wrong_path.write_text(parent._path("parent").read_text(encoding="utf-8"), encoding="utf-8")

    followup = make("followup")
    assert followup.restore("different-run") is False
    assert followup.records == {}


def test_legacy_v1_snapshot_retains_original_expiry_across_followup(run_data):
    make, clock = run_data
    parent = make("legacy")
    ref = record_price(parent, 42)
    parent.save()
    path = parent._path("legacy")
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("record_expires_at")
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    clock.now += 3600
    child = make("child")
    assert child.restore("legacy")
    assert child.rows(ref)[0]["close"] == 42
    assert child.source_refs(ref) == parent.source_refs(ref)
    child.save()

    clock.now = legacy["expires_at"] + 1
    assert make("after-expiry").restore("child") is False
