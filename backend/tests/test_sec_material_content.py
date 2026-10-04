"""8-K/官方附件与明确派息声明的有界离线回归。"""
from types import SimpleNamespace

import pytest

from backend.tools import sec


def _filing(index=1):
    accession = f"0000789019-26-{index:06d}"
    return {"form": "8-K", "filing_url": sec._build_filing_url("0000789019", accession, "event.htm"),
        "accession_number": accession, "filing_date": "2026-09-17", "report_date": "2026-09-16",
        "acceptance_datetime": "2026-09-17T20:01:00Z"}


def _primary():
    return ("<html><body>Microsoft MSFT current report. Item 8.01 Other events. " + "Regulatory filing detail. " * 10
        + '<table><tr><td>EX-99.1</td><td><a href="ex991.htm">Press release</a></td></tr></table></body></html>')


def _declaration(currency="USD", prefix="On September 17, 2026, the Board declared"):
    return (f"Microsoft {prefix} a quarterly cash dividend of {currency}0.91 per common share. "
        "The dividend is payable on December 10, 2026 to shareholders of record on November 19, 2026. "
        + "Company information and official issuer contact details. " * 5)


def test_material_filing_reads_official_exhibit_and_keeps_dividend_provenance(monkeypatch):
    def request(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 8
        return SimpleNamespace(status_code=200, text=_declaration() if url.endswith("ex991.htm") else _primary())
    monkeypatch.setattr(sec, "_http_get_no_retry", request)
    filing = _filing()
    sec._read_material_filing(filing, ticker="MSFT", cik="0000789019", headers={})
    assert filing["content_read"] is True
    assert filing["exhibits"][0]["content_read"] is True
    announcement = filing["dividend_announcements"][0]
    assert announcement["amount_per_share"] == .91
    assert announcement["currency"] == "USD"
    assert announcement["frequency"] == "quarterly"
    assert announcement["announced_at"] == "2026-09-17"
    assert announcement["payable_date"] == "2026-12-10"
    assert announcement["record_date"] == "2026-11-19"
    assert announcement["source_url"].endswith("ex991.htm")
    assert announcement["filing_accepted_at"] == "2026-09-17T20:01:00Z"
    assert filing["announced_at"] is None


@pytest.mark.parametrize("prefix", ["The Board has not declared", "The Board expects to declare"])
def test_negative_or_future_declaration_not_announced(prefix):
    assert sec._dividend_announcement(_declaration(prefix=prefix), subject="MSFT", url="https://www.sec.gov/source", filing=_filing()) is None


def test_dollar_symbol_alone_not_falsely_labelled_as_us_dollars():
    announcement = sec._dividend_announcement(_declaration(currency="$"), subject="MSFT", url="https://www.sec.gov/source", filing=_filing())
    assert announcement["currency"] is None
    assert "currency" in announcement["missing_metrics"]


def test_annual_cash_paid_and_dividend_authorization_not_announcements():
    for body in ["Paid cash dividends of USD3000000 during the year.", "Authorized cash dividends of USD0.5 per share."]:
        assert sec._dividend_announcement(body, subject="MSFT", url="https://www.sec.gov/source", filing=_filing()) is None


def test_exhibits_are_same_issuer_accession_and_at_most_two():
    filing = _filing()
    raw = ('<a href="https://example.com/ex991.htm">99.1</a>'
        '<a href="https://www.sec.gov/Archives/edgar/data/320193/other/ex991.htm">99.1</a>'
        '<a href="%2e%2e/other/ex991.htm">99.1</a>'
        + ''.join(f'<a href="ex99{i}.htm">Exhibit 99.{i}</a>' for i in range(1, 5)))
    urls = sec._material_exhibit_urls(raw, filing, "0000789019")
    assert len(urls) == 2
    assert all(url.startswith(filing["filing_url"].rsplit('/', 1)[0]) for url in urls)


def test_failed_or_captcha_exhibit_is_not_content_read(monkeypatch):
    def request(url, **kwargs):
        return SimpleNamespace(status_code=200, text="CAPTCHA security verification" * 10 if url.endswith("ex991.htm") else _primary())
    monkeypatch.setattr(sec, "_http_get_no_retry", request)
    filing = _filing()
    sec._read_material_filing(filing, ticker="MSFT", cik="0000789019", headers={})
    assert filing["exhibits"][0]["content_read"] is False
    assert not filing["dividend_announcements"]
    assert "announced_dividend" in filing["missing_metrics"]


def test_material_events_include_content_caps_recent_filings_at_six(monkeypatch):
    calls = []
    def fetch(ticker, forms, limit, include_content):
        calls.append((ticker, forms, limit, include_content))
        return {"filings": [{"dividend_announcements": [{"amount_per_share": .91}]}]}
    monkeypatch.setattr(sec, "get_sec_filings", fetch)
    result = sec.get_sec_material_events("MSFT", limit=50, include_content=True)
    assert calls == [("MSFT", ["8-K"], 6, True)]
    assert result["dividend_announcements"][0]["amount_per_share"] == .91
    assert result["announcement_search_state"] == "parsed_declarations_found"
    assert result["coverage"]["exhaustive"] is False


def test_read_without_declaration_is_bounded_search_not_claim_no_announcement(monkeypatch):
    monkeypatch.setattr(sec, "get_sec_filings", lambda **kwargs: {"filings": [{"content_read": True, "dividend_announcements": []}]})
    result = sec.get_sec_material_events("MSFT", include_content=True)
    assert result["announcement_search_state"] == "no_verified_declaration_in_read_documents"
    assert result["coverage"]["filings_read"] == 1
    assert result["coverage"]["exhaustive"] is False


def test_full_sec_filing_path_reads_at_most_six_8ks(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda _: {"MSFT": {"cik": "0000789019", "title": "Microsoft"}})
    monkeypatch.setattr(sec, "_fetch_submissions", lambda *_: {})
    monkeypatch.setattr(sec, "_recent_filings", lambda *a, **k: [_filing(index) for index in range(10)])
    calls = []
    def read(filing, **kwargs):
        calls.append(filing["accession_number"])
        filing["content_read"] = True
    monkeypatch.setattr(sec, "_read_material_filing", read)
    result = sec.get_sec_filings("MSFT", forms="8-K", limit=20, include_content=True)
    assert len(calls) == 6
    assert sum(row.get("content_read", False) for row in result["filings"]) == 6
