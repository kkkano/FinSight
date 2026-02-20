# -*- coding: utf-8 -*-
import backend.tools.earnings_transcripts as transcripts_mod


def test_get_earnings_call_transcripts_cn_market_builds_cn_queries(monkeypatch):
    captured_queries: list[str] = []

    def _fake_search(query: str) -> str:
        captured_queries.append(query)
        return ""

    monkeypatch.setattr(transcripts_mod, "search", _fake_search)

    payload = transcripts_mod.get_earnings_call_transcripts("600519.SS", limit=3)

    assert payload.get("market") == "CN"
    assert payload.get("count") == 0
    assert any("业绩说明会" in query for query in captured_queries)
    assert any("电话会议" in query for query in captured_queries)


def test_get_earnings_call_transcripts_cn_market_parses_chinese_row(monkeypatch):
    raw = (
        "[贵州茅台 业绩说明会 纪要]"
        "(https://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519)"
    )
    monkeypatch.setattr(transcripts_mod, "search", lambda _query: raw)
    monkeypatch.setattr(transcripts_mod, "_maybe_enrich_snippet", lambda _url, snippet: snippet)

    payload = transcripts_mod.get_earnings_call_transcripts("600519.SS", limit=3)

    assert payload.get("market") == "CN"
    assert payload.get("count", 0) >= 1
    row = payload.get("transcripts")[0]
    assert row.get("domain") == "cninfo.com.cn"
    assert row.get("type") == "transcript"


def test_get_earnings_call_transcripts_hk_market_parses_results_presentation(monkeypatch):
    raw = (
        "[Tencent FY2025 results presentation transcript]"
        "(https://www.hkexnews.hk/listedco/listconews/sehk/2026/0210/2026021000012.pdf)"
    )
    monkeypatch.setattr(transcripts_mod, "search", lambda _query: raw)
    monkeypatch.setattr(transcripts_mod, "_maybe_enrich_snippet", lambda _url, snippet: snippet)

    payload = transcripts_mod.get_earnings_call_transcripts("0700.HK", limit=3)

    assert payload.get("market") == "HK"
    assert payload.get("count", 0) >= 1
    row = payload.get("transcripts")[0]
    assert "hkexnews.hk" in str(row.get("domain") or "")
    assert row.get("type") == "transcript"
