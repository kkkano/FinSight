"""只允许在 finsight_test_* 隔离数据库运行的真实 PostgreSQL 事务验收。

FINSIGHT_TEST_POSTGRES_DSN 未设置时跳过，不读取任何生产 DSN。
建议用拥有测试库的非 superuser 角色运行，以同时验证 FORCE RLS。
"""
from __future__ import annotations

import importlib.util
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.services.conversation_store import ConversationVersionConflict, PostgresConversationStore
from backend.services.database import normalize_sync_postgres_dsn
from backend.services.research_run_store import PostgresResearchRunStore, ResearchRunConflict, request_fingerprint


@pytest.fixture
def stores():
    raw = os.getenv("FINSIGHT_TEST_POSTGRES_DSN", "")
    if not raw:
        pytest.skip("未配置隔离 FINSIGHT_TEST_POSTGRES_DSN")
    dsn = normalize_sync_postgres_dsn(raw)
    if not str(make_url(dsn).database or "").startswith("finsight_test_"):
        pytest.fail("只允许 finsight_test_* 数据库，拒绝在业务数据库执行验收")
    schema = "delivery_" + uuid.uuid4().hex
    admin = create_engine(dsn)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE conversation_threads (
                    user_id TEXT NOT NULL,session_id TEXT NOT NULL,title TEXT NOT NULL,
                    messages JSONB NOT NULL DEFAULT '[]'::jsonb,message_count INTEGER NOT NULL DEFAULT 0,
                    last_message_preview TEXT NOT NULL DEFAULT '',pinned BOOLEAN NOT NULL DEFAULT false,
                    archived BOOLEAN NOT NULL DEFAULT false,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(user_id,session_id)
                )
            """))
            # 升级前先写真实旧行，验证新增迁移不重写历史。
            conn.execute(text("INSERT INTO conversation_threads(user_id,session_id,title,messages,message_count) "
                              "VALUES ('alice','public:alice:legacy','旧会话','[{\"role\":\"user\",\"content\":\"历史正文\"}]',1)"))
            path = Path(__file__).resolve().parents[2] / "migrations/versions/20261003_0005_research_delivery.py"
            spec = importlib.util.spec_from_file_location("delivery_migration_test", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            migration.op = SimpleNamespace(execute=lambda sql: conn.execute(text(sql)))
            migration.upgrade()
        yield PostgresResearchRunStore(engine=engine), PostgresConversationStore(engine=engine), engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def begin(store, *, run="run-1", user_message="u-1", assistant_message="a-1", owner="alice", query="真实问题"):
    return store.begin(user_id=owner, run_id=run, session_id=f"public:{owner}:thread", query=query,
                       fingerprint=request_fingerprint({"query": query}), user_message_id=user_message,
                       assistant_message_id=assistant_message)


def finish(store, *, run="run-1", answer="完整答案", owner="alice"):
    return store.finish(run, {"type": "done", "response": answer, "publishable": True, "answer_status": "answered"}, user_id=owner)


def test_upgrade_preserves_history_and_enables_owner_rls(stores):
    _runs, conversations, engine = stores
    old = conversations.get("public:alice:legacy", "alice")
    assert old["messages"] == [{"role": "user", "content": "历史正文"}]
    assert old["version"] == 0
    with engine.connect() as conn:
        policies = conn.execute(text("SELECT tablename FROM pg_policies WHERE schemaname=current_schema() ORDER BY tablename")).scalars().all()
        assert policies == ["conversation_messages", "research_runs"]
        flags = conn.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                                  "WHERE relnamespace=current_schema()::regnamespace AND relname IN ('research_runs','conversation_messages')")).all()
        assert flags == [(True, True), (True, True)]


def test_atomic_final_message_duplicate_done_and_stale_snapshot(stores):
    runs, conversations, _engine = stores
    row, created = begin(runs)
    assert created and row["status"] == "running"
    placeholder = conversations.get("public:alice:thread", "alice")
    assert placeholder["messages"][1]["isLoading"] is True
    assert placeholder["messages"][1]["run_id"] == "run-1"
    done = finish(runs)
    duplicate = finish(runs, answer="不允许覆盖已冻结的答案")
    assert duplicate == done
    assert done["persistence_status"] == "saved"
    assert done["assistant_message"]["content"] == "完整答案"
    conversations.upsert("public:alice:thread", {"messages": [{"id": "u-1", "role": "user", "content": "真实问题"},
                         {"id": "a-1", "role": "assistant", "content": "被截断的旧快照"}]}, "alice")
    restored = conversations.get("public:alice:thread", "alice")
    assert len(restored["messages"]) == 2 and restored["messages"][1]["content"] == "完整答案"
    with pytest.raises(ConversationVersionConflict):
        conversations.upsert("public:alice:thread", {"messages": [], "expected_version": 0}, "alice")


def test_message_id_conflict_rolls_back_run_and_does_not_mutate_history(stores):
    runs, conversations, _engine = stores
    begin(runs)
    before = conversations.get("public:alice:thread", "alice")
    with pytest.raises(ResearchRunConflict):
        begin(runs, run="conflicting", assistant_message="a-2", query="different")
    assert runs.get("conflicting", user_id="alice") is None
    assert conversations.get("public:alice:thread", "alice") == before


def test_two_workers_racing_same_run_pay_only_once(stores):
    runs, conversations, _engine = stores
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: begin(runs), range(2)))
    assert sorted(created for _row, created in results) == [False, True]
    assert len(conversations.get("public:alice:thread", "alice")["messages"]) == 2


def test_retry_replaces_visible_reply_and_late_old_run_cannot_overwrite(stores):
    runs, conversations, _engine = stores
    begin(runs)
    begin(runs, run="retry-run", assistant_message="retry-assistant")
    finish(runs, run="retry-run", answer="新回答")
    finish(runs, answer="迟到旧回答")
    visible = conversations.get("public:alice:thread", "alice")["messages"]
    assert [message["id"] for message in visible] == ["u-1", "retry-assistant"]
    assert visible[1]["content"] == "新回答"
    assert runs.get("run-1", user_id="alice")["final_payload"]["response"] == "迟到旧回答"


def test_expired_lease_becomes_interrupted_and_cannot_resume_paid_work(stores):
    runs, conversations, engine = stores
    begin(runs)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_user_id','alice',true)"))
        conn.execute(text("UPDATE research_runs SET lease_expires_at=now()-interval '1 second' WHERE user_id='alice' AND run_id='run-1'"))
    recovered = runs.get("run-1", user_id="alice")
    assert recovered["status"] == "interrupted"
    assert recovered["final_payload"]["code"] == "run_interrupted"
    assert conversations.get("public:alice:thread", "alice")["messages"][1]["canRetry"] is True
    row, created = begin(runs)
    assert not created and row["status"] == "interrupted"
    assert finish(runs)["run_status"] == "interrupted"


def test_owner_isolation_and_delete_cascade(stores):
    runs, conversations, _engine = stores
    begin(runs)
    assert runs.get("run-1", user_id="bob") is None
    assert conversations.get("public:alice:thread", "bob") is None
    with pytest.raises(ResearchRunConflict):
        runs.finish("run-1", {"type": "done", "response": "forged"}, user_id="bob")
    assert conversations.delete("public:alice:thread", "alice")
    assert runs.get("run-1", user_id="alice") is None


def test_missing_rls_owner_cannot_read_messages_for_non_superuser(stores):
    runs, _conversations, engine = stores
    begin(runs)
    with engine.begin() as conn:
        if conn.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one():
            pytest.skip("需非 superuser/BYPASSRLS 测试角色验证数据库拒绝跨租户查询")
        assert conn.execute(text("SELECT count(*) FROM research_runs")).scalar_one() == 0
        conn.execute(text("SELECT set_config('app.current_user_id','bob',true)"))
        assert conn.execute(text("SELECT count(*) FROM conversation_messages")).scalar_one() == 0
