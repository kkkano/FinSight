"""账户报告目录在隔离真实 PostgreSQL 中保留跨会话可见性和 owner 边界。"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.services.database import normalize_sync_postgres_dsn
from backend.services.report_index import ReportIndexStore


def test_account_directory_and_replay_do_not_cross_owners():
    raw = os.getenv("FINSIGHT_TEST_POSTGRES_DSN")
    if not raw:
        pytest.skip("未配置隔离 PostgreSQL 测试库")
    dsn = normalize_sync_postgres_dsn(raw)
    if not str(make_url(dsn).database or "").startswith("finsight_test_"):
        pytest.fail("拒绝使用业务数据库")
    engine = create_engine(dsn)
    store = ReportIndexStore(engine=engine)
    first, second = "test-a-" + uuid4().hex, "test-b-" + uuid4().hex
    reports = [(first, "first", "rpt-" + uuid4().hex), (first, "second", "rpt-" + uuid4().hex), (second, "other", "rpt-" + uuid4().hex)]
    try:
        for owner, session, report_id in reports:
            store.upsert_report(session_id=f"web:{owner}:{session}", user_id=owner,
                report={"report_id": report_id, "title": session, "report_quality": {"state": "pass", "reasons": []},
                        "citations": [{"source_id": "source", "url": "https://example.com/filing", "title": "原始资料"}]})
        assert {row["report_id"] for row in store.list_reports(user_id=first)} == {row[2] for row in reports[:2]}
        replay = store.get_report_replay(user_id=first, report_id=reports[1][2])
        assert replay["session_id"].endswith(":second") and replay["citations"][0]["url"]
        assert store.get_report_replay(user_id=first, report_id=reports[2][2]) is None
        assert store.get_report_replay(user_id=first, session_id=f"web:{first}:first", report_id=reports[1][2]) is None
    finally:
        with engine.begin() as connection:
            for owner in (first, second):
                connection.execute(text("DELETE FROM report_citations WHERE user_id=:owner"), {"owner": owner})
                connection.execute(text("DELETE FROM reports WHERE user_id=:owner"), {"owner": owner})
        engine.dispose()
