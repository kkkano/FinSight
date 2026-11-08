"""使用显式 finsight_test_* 数据库验证运行快照的真实事务边界。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.services.research_run_store import ResearchRunConflict
from backend.tests.test_research_run_postgres import begin, finish, stores


def snapshot(seq: int, content: str = "已提交前缀") -> dict:
    return {
        "attempt_id": "test-attempt",
        "stream_epoch": "test-epoch",
        "committed_seq": seq,
        "response": content,
        "blocks": [{"id": "answer", "kind": "text", "content": content, "revision": 0}],
        "artifacts": [],
    }


def test_checkpoint_watermark_and_snapshot_remain_consistent(stores):
    runs, conversations, _engine = stores
    begin(runs)
    first = snapshot(10)
    first["blocks"].append({"id": "private", "kind": "provider_raw", "content": "不保存"})
    committed = runs.checkpoint("run-1", first, user_id="alice")
    visible = conversations.get("public:alice:thread", "alice")
    assert committed["blocks"] == snapshot(10)["blocks"]
    assert visible["messages"][1]["runtime_snapshot"] == committed
    assert visible["messages"][1]["content"] == "已提交前缀"

    for seq in (9, 10):
        assert runs.checkpoint("run-1", snapshot(seq, "迟到内容"), user_id="alice") == committed
        assert conversations.get("public:alice:thread", "alice") == visible

    latest = runs.checkpoint("run-1", snapshot(11, "更新的前缀"), user_id="alice")
    assert runs.get_checkpoint("run-1", user_id="alice") == latest
    assert latest["committed_seq"] == 11
    assert conversations.get("public:alice:thread", "alice")["messages"][1]["content"] == "更新的前缀"


def test_checkpoint_rejects_cross_owner_and_foreign_worker(stores):
    runs, _conversations, engine = stores
    begin(runs)
    committed = runs.checkpoint("run-1", snapshot(10), user_id="alice")
    assert runs.get_checkpoint("run-1", user_id="bob") is None
    with pytest.raises(ResearchRunConflict):
        runs.checkpoint("run-1", snapshot(11), user_id="bob")
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_user_id','alice',true)"))
        conn.execute(text("UPDATE research_runs SET worker_id='other-test-worker' WHERE run_id='run-1'"))
    with pytest.raises(ResearchRunConflict):
        runs.checkpoint("run-1", snapshot(11), user_id="alice")
    assert runs.get_checkpoint("run-1", user_id="alice") == committed
    assert runs.heartbeat("run-1", user_id="alice") is False


def test_checkpoint_and_final_race_freezes_whole_payload(stores):
    runs, conversations, _engine = stores
    begin(runs)
    runs.checkpoint("run-1", snapshot(10), user_id="alice")
    artifact = {"artifact_id": "chart-1", "kind": "chart", "title": "价格图"}
    action = {"action_id": "action-1", "action": "watchlist.add", "status": "proposed"}
    final_blocks = snapshot(20, "完整最终答案")["blocks"] + [
        {"id": "chart-1", "kind": "artifact", "artifact": artifact},
        {"id": "action-1", "kind": "action", "action": action},
    ]
    event = {"type": "done", "response": "完整最终答案", "publishable": True,
             "blocks": final_blocks, "artifacts": [artifact], "actions": [action]}
    barrier = Barrier(2)

    def write_checkpoint():
        barrier.wait(timeout=5)
        try:
            return runs.checkpoint("run-1", snapshot(11, "并发前缀"), user_id="alice")
        except ResearchRunConflict:
            return None

    def write_final():
        barrier.wait(timeout=5)
        return runs.finish("run-1", event, user_id="alice")

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_checkpoint = pool.submit(write_checkpoint)
        pending_final = pool.submit(write_final)
        pending_checkpoint.result(timeout=15)
        final = pending_final.result(timeout=15)

    assert final["persistence_status"] == "saved"
    visible = conversations.get("public:alice:thread", "alice")["messages"][1]
    assert visible["content"] == "完整最终答案"
    assert visible["blocks"] == final_blocks
    assert visible["artifacts"] == [artifact]
    assert visible["actions"] == [action]
    assert visible["isLoading"] is False
    with pytest.raises(ResearchRunConflict):
        runs.checkpoint("run-1", snapshot(100, "迟到旧快照"), user_id="alice")
    assert finish(runs, answer="重复完成事件") == final
    assert conversations.get("public:alice:thread", "alice")["messages"][1] == visible


def test_expired_lease_preserves_committed_prefix_and_artifacts(stores):
    runs, conversations, engine = stores
    begin(runs)
    prefix = snapshot(10)
    artifact = {"artifact_id": "table-1", "kind": "table", "title": "已完成表格"}
    prefix["artifacts"] = [artifact]
    prefix["blocks"].append({"id": "table-1", "kind": "artifact", "artifact": artifact})
    runs.checkpoint("run-1", prefix, user_id="alice")
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_user_id','alice',true)"))
        conn.execute(text("UPDATE research_runs SET lease_expires_at=now()-interval '1 second' WHERE run_id='run-1'"))
    recovered = runs.get("run-1", user_id="alice")
    assert recovered["status"] == "interrupted"
    assert recovered["final_payload"]["response"] == prefix["response"]
    visible = conversations.get("public:alice:thread", "alice")["messages"][1]
    assert visible["content"] == prefix["response"]
    assert visible["blocks"] == prefix["blocks"]
    assert visible["artifacts"] == prefix["artifacts"]
    assert visible["canRetry"] is True and visible["publishable"] is False
    with pytest.raises(ResearchRunConflict):
        runs.checkpoint("run-1", snapshot(11), user_id="alice")
    assert finish(runs) == recovered["final_payload"]


def test_database_commit_rejection_rolls_back_prefix_and_terminal(stores):
    runs, conversations, engine = stores
    begin(runs)
    committed = runs.checkpoint("run-1", snapshot(10), user_id="alice")
    visible = conversations.get("public:alice:thread", "alice")
    # 延迟约束触发器使错误发生在 COMMIT，而不是业务 SQL 执行期间。
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE FUNCTION reject_test_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='test deferred commit rejection';
            END;
            $$
        """))
        conn.execute(text("""
            CREATE CONSTRAINT TRIGGER reject_test_commit
            AFTER UPDATE ON conversation_threads DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION reject_test_commit()
        """))

    with pytest.raises(IntegrityError, match="test deferred commit rejection"):
        runs.checkpoint("run-1", snapshot(11, "不能提交的前缀"), user_id="alice")
    assert runs.get_checkpoint("run-1", user_id="alice") == committed
    assert conversations.get("public:alice:thread", "alice") == visible

    with pytest.raises(IntegrityError, match="test deferred commit rejection"):
        finish(runs)
    row = runs.get("run-1", user_id="alice")
    assert row["status"] == "running" and row["final_payload"] is None
    assert runs.get_checkpoint("run-1", user_id="alice") == committed
    assert conversations.get("public:alice:thread", "alice") == visible


def _begin_followup_run(runs, run_id, *, owner="alice", session="thread"):
    return runs.begin(
        user_id=owner, run_id=run_id, session_id=f"public:{owner}:{session}",
        query="补充分析此前资料", fingerprint=run_id,
        user_message_id=f"u-{run_id}", assistant_message_id=f"a-{run_id}",
    )


def test_previous_run_id_uses_sequence_and_excludes_current_and_later_runs(stores):
    runs, _conversations, engine = stores
    for run_id in ("first", "previous", "current", "later"):
        _begin_followup_run(runs, run_id)
        finish(runs, run=run_id)

    # 时间戳相同也必须按服务器运行序号判断，不能选到当前或之后的运行。
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_user_id','alice',true)"))
        conn.execute(text("UPDATE research_runs SET created_at='2026-01-01T00:00:00Z' WHERE user_id='alice'"))

    assert runs.previous_run_id("public:alice:thread", "current", user_id="alice") == "previous"
    assert runs.previous_run_id("public:alice:thread", "first", user_id="alice") is None


@pytest.mark.parametrize("candidate_status", [
    "completed", "failed", "interrupted", "running", "cancelled", "persistence_failed",
])
def test_previous_run_id_only_selects_allowed_terminal_statuses_without_recovering(stores, candidate_status):
    runs, _conversations, engine = stores
    _begin_followup_run(runs, "older")
    finish(runs, run="older")
    _begin_followup_run(runs, "candidate")
    if candidate_status == "running":
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_user_id','alice',true)"))
            conn.execute(text("UPDATE research_runs SET lease_expires_at=now()-interval '1 second' "
                              "WHERE user_id='alice' AND run_id='candidate'"))
    else:
        runs.finish("candidate", {"type": "done", "run_status": candidate_status,
                                  "response": "此前已提交资料"}, user_id="alice")
    _begin_followup_run(runs, "current")
    before = runs.get("candidate", user_id="alice", recover_expired=False)

    expected = "candidate" if candidate_status in {"completed", "failed", "interrupted"} else "older"
    assert runs.previous_run_id("public:alice:thread", "current", user_id="alice") == expected
    assert runs.get("candidate", user_id="alice", recover_expired=False) == before
    assert runs.get("current", user_id="alice", recover_expired=False)["status"] == "running"


def test_previous_run_id_requires_same_owner_session_and_existing_anchor(stores):
    runs, _conversations, _engine = stores
    _begin_followup_run(runs, "alice-parent")
    finish(runs, run="alice-parent")
    _begin_followup_run(runs, "bob-parent", owner="bob")
    finish(runs, run="bob-parent", owner="bob")
    _begin_followup_run(runs, "other-session-parent", session="other")
    finish(runs, run="other-session-parent")
    _begin_followup_run(runs, "alice-anchor")
    _begin_followup_run(runs, "bob-anchor", owner="bob")

    assert runs.previous_run_id("public:alice:thread", "alice-anchor", user_id="alice") == "alice-parent"
    assert runs.previous_run_id("public:bob:thread", "bob-anchor", user_id="bob") == "bob-parent"
    assert runs.previous_run_id("public:alice:other", "alice-anchor", user_id="alice") is None
    assert runs.previous_run_id("public:alice:thread", "alice-anchor", user_id="bob") is None
    assert runs.previous_run_id("public:alice:thread", "bob-anchor", user_id="alice") is None
    assert runs.previous_run_id("public:alice:thread", "missing", user_id="alice") is None


def test_provider_reasoning_is_bounded_and_only_readable_by_owner(stores):
    runs, conversations, _engine = stores
    begin(runs)
    blocks = [{"id": f"thought-{i}", "kind": "reasoning", "reasoning_kind": "provider_raw", "content": "本人思考" * 5000,
               "seq": i + 1, "agent_id": "root"} for i in range(2)]
    step = {"stage": "tool.result", "timestamp": "2026-11-07T00:00:00Z", "runId": "run-1", "sessionId": "public:alice:thread",
            "result": {"runtime_type": "tool.result", "tool_call_id": "call-1", "name": "get_stock_price",
                       "seq": 3, "display": {"target": "AAPL", "result": "已取得真实行情"}}}
    checkpoint = snapshot(4, "公开正文")
    checkpoint.update(blocks=blocks, thinking=[step])
    saved = runs.checkpoint("run-1", checkpoint, user_id="alice")
    assert sum(len(block["content"]) for block in saved["blocks"]) == 20000
    assert saved["blocks"][-1]["truncated"] is True
    assert runs.get_checkpoint("run-1", user_id="bob") is None
    assert conversations.get("public:alice:thread", "bob") is None
    result = runs.finish("run-1", {"type": "done", "response": "公开正文", "blocks": blocks, "thinking": [step]}, user_id="alice")
    message = result["assistant_message"]
    assert message["content"] == "公开正文"
    assert sum(len(block["content"]) for block in message["blocks"]) == 20000
    assert sum(len(block["content"]) for block in result["blocks"]) == 20000
    assert message["thinking"][0]["result"]["display"]["target"] == "AAPL"
    assert runs.get("run-1", user_id="bob") is None
