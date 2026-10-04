# -*- coding: utf-8 -*-
import backend.tools.earnings_transcripts as transcripts_mod
import pytest


@pytest.fixture(autouse=True)
def no_network_documents(monkeypatch):
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: None)


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

    payload = transcripts_mod.get_earnings_call_transcripts("0700.HK", limit=3)

    assert payload.get("market") == "HK"
    assert payload.get("count", 0) >= 1
    row = payload.get("transcripts")[0]
    assert "hkexnews.hk" in str(row.get("domain") or "")
    assert row.get("type") == "transcript"


def test_transcript_rejects_similar_numeric_ticker_and_wrong_company(monkeypatch):
    raw = "[InSilico Medicine HKG:3696 earnings transcript](https://stockanalysis.com/quote/hkg/3696/transcripts/123/)"
    monkeypatch.setattr(transcripts_mod, "search", lambda _: raw)
    result = transcripts_mod.get_earnings_call_transcripts("3690.HK")
    assert result["count"] == 0
    assert result["rejected_candidates"][0]["reason"] == "issuer_not_verified"


def test_transcript_rejects_captcha_and_registration_body(monkeypatch):
    raw = "[MSFT earnings call transcript](https://example.com/msft/transcript)"
    monkeypatch.setattr(transcripts_mod, "search", lambda _: raw)
    for body in ["Title: Just a moment... CAPTCHA Performing security verification", "Please register to access our event summary Guest Registration"]:
        monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: {"content": body})
        result = transcripts_mod.get_earnings_call_transcripts("MSFT")
        assert result["count"] == 0
        assert result["rejected_candidates"][0]["reason"] == "blocked_content"


def test_title_is_not_enough_when_enriched_body_belongs_to_other_issuer(monkeypatch):
    raw = "[MSFT earnings call transcript](https://example.com/msft/transcript)"
    monkeypatch.setattr(transcripts_mod, "search", lambda _: raw)
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: {"content": "Apple AAPL earnings call transcript"})
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    assert result["count"] == 0
    assert result["rejected_candidates"][0]["reason"] == "body_issuer_not_verified"


def test_discovery_snippet_does_not_claim_read_full_transcript(monkeypatch):
    raw = "[Microsoft MSFT earnings call transcript](https://example.com/transcript)"
    monkeypatch.setattr(transcripts_mod, "search", lambda _: raw)
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    assert result["count"] == 1
    assert result["transcripts"][0]["content_read"] is False
    assert result["transcripts"][0]["verification"] == "issuer_verified_discovery"


def _body(issuer="Microsoft MSFT", quarter="Q4 2026"):
    return (f"{issuer} {quarter} earnings call transcript\nPublished Time: 2026-07-30\n"
        "Operator\nWelcome to the quarterly earnings conference call.\n"
        "Jane Doe - Chief Financial Officer\n" + "Revenue growth and capital spending reflect actual business demand. " * 25)


def test_verified_body_preserves_management_text_period_and_publication_date(monkeypatch):
    monkeypatch.setattr(transcripts_mod, "search", lambda _: "[Microsoft MSFT Q4 2026 earnings call transcript](https://example.com/new/transcript)")
    body = _body()
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: {"content": body, "retrieval_method": "http_document"})
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    row = result["transcripts"][0]
    assert row["content_read"] is True
    assert row["body"] == body
    assert len(row["snippet"]) > 800
    assert row["fiscal_period"]["fiscal_year"] == 2026
    assert row["fiscal_period"]["fiscal_quarter"] == 4
    assert row["published_date"] == "2026-07-30"
    assert row["verification"] == "issuer_and_body_verified"
    assert row["structured_data"]["body"] == body


def test_newest_fiscal_period_prioritized_and_body_read_budget_bounded(monkeypatch):
    rows = [f"[MSFT Q{quarter} 2026 earnings transcript](https://example.com/q{quarter}/transcript)" for quarter in [1, 4, 2, 3]]
    monkeypatch.setattr(transcripts_mod, "search", lambda _: "\n".join(rows))
    calls = []
    def fetch(url):
        calls.append(url)
        quarter = url.split("/q", 1)[1][0]
        return {"content": _body(quarter=f"Q{quarter} 2026")}
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", fetch)
    result = transcripts_mod.get_earnings_call_transcripts("MSFT", limit=4)
    assert len(calls) == 2
    assert calls[0].endswith("/q4/transcript")
    assert calls[1].endswith("/q3/transcript")
    assert sum(row["content_read"] for row in result["transcripts"]) == 2


def test_long_search_snippet_cannot_replace_an_actual_body_read(monkeypatch):
    raw = f"[MSFT earnings call transcript {'growth ' * 100}](https://example.com/transcript)"
    monkeypatch.setattr(transcripts_mod, "search", lambda _: raw)
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    assert result["transcripts"][0]["content_read"] is False


def test_body_with_competing_issuer_listing_is_rejected_even_if_msft_mentioned(monkeypatch):
    monkeypatch.setattr(transcripts_mod, "search", lambda _: "[MSFT earnings call transcript](https://example.com/transcript)")
    body = _body("Apple NASDAQ:AAPL") + "Microsoft MSFT is one of our competitors."
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: {"content": body})
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    assert result["count"] == 0


def test_unsafe_url_is_never_sent_to_http_or_jina(monkeypatch):
    monkeypatch.setattr(transcripts_mod, "is_safe_url", lambda _: False)
    monkeypatch.setattr(transcripts_mod, "fetch_url_document", lambda *a, **k: pytest.fail("unsafe HTTP"))
    monkeypatch.setattr(transcripts_mod, "fetch_via_jina", lambda *a, **k: pytest.fail("unsafe Jina"))
    assert _ORIGINAL_FETCH("http://127.0.0.1/internal") is None


def test_search_title_quarter_cannot_override_actual_different_body_quarter(monkeypatch):
    monkeypatch.setattr(transcripts_mod, "search", lambda _: "[MSFT Q4 2026 earnings call transcript](https://example.com/transcript)")
    monkeypatch.setattr(transcripts_mod, "_fetch_transcript_document", lambda _: {"content": _body(quarter="Q1 2025")})
    result = transcripts_mod.get_earnings_call_transcripts("MSFT")
    assert result["count"] == 0
    assert result["rejected_candidates"][0]["reason"] == "fiscal_period_mismatch"


_ORIGINAL_FETCH = transcripts_mod._fetch_transcript_document
