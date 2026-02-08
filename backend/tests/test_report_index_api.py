# -*- coding: utf-8 -*-
import importlib

from fastapi.testclient import TestClient


def _load_main_module():
    import backend.api.main as main

    importlib.reload(main)
    return main


def test_report_index_list_replay_and_favorite_flow(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "report_index.sqlite"
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(sqlite_path))

    main = _load_main_module()
    store = main.get_report_index_store()

    session_id = "tenant1:user1:thread1"
    report = {
        "report_id": "rpt-001",
        "ticker": "AAPL",
        "title": "AAPL 深度报告",
        "summary": "summary",
        "generated_at": "2026-02-07T00:00:00Z",
        "citations": [
            {
                "source_id": "src-1",
                "title": "citation-title",
                "url": "https://example.com/c1",
                "snippet": "snippet",
            }
        ],
    }
    store.upsert_report(session_id=session_id, report=report, trace_digest={"span_count": 3})

    client = TestClient(main.app)

    list_resp = client.get(
        "/api/reports/index",
        params={"session_id": session_id, "limit": 10},
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data.get("success") is True
    assert list_data.get("count") == 1
    assert list_data["items"][0]["report_id"] == "rpt-001"

    replay_resp = client.get(
        "/api/reports/replay/rpt-001",
        params={"session_id": session_id},
    )
    assert replay_resp.status_code == 200
    replay_data = replay_resp.json()
    assert replay_data.get("success") is True
    assert replay_data.get("report", {}).get("report_id") == "rpt-001"
    assert isinstance(replay_data.get("citations"), list)

    fav_resp = client.post(
        "/api/reports/rpt-001/favorite",
        json={"session_id": session_id, "is_favorite": True},
    )
    assert fav_resp.status_code == 200
    fav_data = fav_resp.json()
    assert fav_data.get("is_favorite") is True


def test_report_index_supports_date_tag_filters_and_normalizes_source_id(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "report_index.sqlite"
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(sqlite_path))

    main = _load_main_module()
    store = main.get_report_index_store()
    client = TestClient(main.app)

    session_id = "tenant2:user2:thread2"

    store.upsert_report(
        session_id=session_id,
        report={
            "report_id": "rpt-ai-1",
            "ticker": "AAPL",
            "title": "AI 主题研报",
            "summary": "focus on ai",
            "tags": ["ai", "us-tech"],
            "generated_at": "2026-02-06T09:00:00Z",
            "citations": [
                {
                    "source_id": "legacy-source-id",
                    "title": "Apple AI Update",
                    "url": "https://example.com/apple-ai",
                    "snippet": "Apple shipped new AI features",
                }
            ],
        },
        trace_digest={"span_count": 2},
    )

    store.upsert_report(
        session_id=session_id,
        report={
            "report_id": "rpt-macro-1",
            "ticker": "MSFT",
            "title": "宏观观察",
            "summary": "macro view",
            "tags": ["macro"],
            "generated_at": "2026-02-08T12:30:00Z",
            "citations": [
                {
                    "title": "Macro Source",
                    "url": "https://example.com/macro",
                    "snippet": "macro news",
                }
            ],
        },
        trace_digest={"span_count": 1},
    )

    tag_resp = client.get(
        "/api/reports/index",
        params={"session_id": session_id, "tag": "ai", "limit": 10},
    )
    assert tag_resp.status_code == 200
    tag_data = tag_resp.json()
    assert tag_data.get("count") == 1
    assert tag_data["items"][0]["report_id"] == "rpt-ai-1"

    date_resp = client.get(
        "/api/reports/index",
        params={
            "session_id": session_id,
            "date_from": "2026-02-08T00:00:00Z",
            "date_to": "2026-02-08T23:59:59Z",
            "limit": 10,
        },
    )
    assert date_resp.status_code == 200
    date_data = date_resp.json()
    assert date_data.get("count") == 1
    assert date_data["items"][0]["report_id"] == "rpt-macro-1"

    replay_resp = client.get(
        "/api/reports/replay/rpt-ai-1",
        params={"session_id": session_id},
    )
    assert replay_resp.status_code == 200
    replay_data = replay_resp.json()
    citations = replay_data.get("citations") or []
    assert citations
    citation = citations[0]
    assert str(citation.get("source_id") or "").startswith("src_")
    assert citation.get("source_id_consistent") is False
    assert citation.get("source_id_original") == "legacy-source-id"


def test_report_citation_index_filters_by_source_and_query(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "report_index.sqlite"
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(sqlite_path))

    main = _load_main_module()
    store = main.get_report_index_store()
    client = TestClient(main.app)

    session_id = "tenant3:user3:thread3"

    report = {
        "report_id": "rpt-cit-1",
        "ticker": "AAPL",
        "title": "Citation Query Report",
        "summary": "summary",
        "generated_at": "2026-02-08T10:00:00Z",
        "citations": [
            {
                "title": "Apple source",
                "url": "https://example.com/apple",
                "snippet": "Apple earnings beat",
                "published_date": "2026-02-08T09:00:00Z",
            },
            {
                "title": "Macro source",
                "url": "https://example.com/macro",
                "snippet": "Macro pressure remains",
                "published_date": "2026-02-07T09:00:00Z",
            },
        ],
    }
    store.upsert_report(session_id=session_id, report=report, trace_digest={"span_count": 1})

    replay_resp = client.get(
        "/api/reports/replay/rpt-cit-1",
        params={"session_id": session_id},
    )
    assert replay_resp.status_code == 200
    replay_data = replay_resp.json()
    citations = replay_data.get("citations") or []
    assert len(citations) == 2
    first_source_id = str(citations[0].get("source_id") or "").strip()
    assert first_source_id.startswith("src_")

    query_resp = client.get(
        "/api/reports/citations",
        params={"session_id": session_id, "query": "earnings", "limit": 20},
    )
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data.get("count") == 1
    assert "earnings" in str(query_data["items"][0].get("snippet") or "").lower()

    source_resp = client.get(
        "/api/reports/citations",
        params={"session_id": session_id, "source_id": first_source_id, "limit": 20},
    )
    assert source_resp.status_code == 200
    source_data = source_resp.json()
    assert source_data.get("count") == 1
    assert source_data["items"][0].get("source_id") == first_source_id
