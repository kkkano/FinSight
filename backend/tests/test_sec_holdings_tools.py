# -*- coding: utf-8 -*-
import backend.tools.sec as sec
import backend.tools.sec_holdings as sec_holdings


class _FakeResponse:
    def __init__(self, status_code: int, json_payload=None, text: str = ""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text

    def json(self):
        return self._json_payload


def _reset_sec_cache() -> None:
    sec._ticker_cache = {}
    sec._ticker_cache_expire_at = 0.0


def _ticker_map_payload():
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
        "2": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp."},
    }


def test_get_institutional_holdings_rejects_non_us_market(monkeypatch):
    _reset_sec_cache()
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight admin@finsight.app")

    payload = sec_holdings.get_institutional_holdings("600519.SS")

    assert payload.get("error") == "unsupported_market"
    assert payload.get("market") == "CN"
    assert payload.get("supported_market") == "US"


def test_get_institutional_holdings_requires_sec_user_agent(monkeypatch):
    _reset_sec_cache()
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    payload = sec_holdings.get_institutional_holdings("0001067983")

    assert payload.get("error") == "missing_sec_user_agent"
    assert payload.get("supported_market") == "US"


def test_get_institutional_holdings_parses_13f_infotable_xml(monkeypatch):
    _reset_sec_cache()
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight admin@finsight.app")

    info_table_xml = """<?xml version="1.0"?>
    <informationTable>
      <infoTable>
        <nameOfIssuer>Apple Inc.</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip>
        <value>150000</value>
        <shrsOrPrnAmt>
          <sshPrnamt>1000</sshPrnamt>
          <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority>
          <Sole>1000</Sole>
          <Shared>0</Shared>
          <None>0</None>
        </votingAuthority>
      </infoTable>
      <infoTable>
        <nameOfIssuer>NVIDIA Corp.</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>67066G104</cusip>
        <value>75000</value>
        <shrsOrPrnAmt>
          <sshPrnamt>250</sshPrnamt>
          <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>DFND</investmentDiscretion>
      </infoTable>
    </informationTable>
    """

    def _fake_http_get(url, **kwargs):
        if url.endswith("company_tickers.json"):
            return _FakeResponse(200, _ticker_map_payload())
        if "submissions/CIK0001067983.json" in url:
            return _FakeResponse(
                200,
                {
                    "name": "BERKSHIRE HATHAWAY INC",
                    "filings": {
                        "recent": {
                            "form": ["13F-HR", "10-K"],
                            "filingDate": ["2025-05-15", "2025-02-20"],
                            "reportDate": ["2025-03-31", "2024-12-31"],
                            "acceptanceDateTime": ["2025-05-15T12:00:00.000Z", "2025-02-20T12:00:00.000Z"],
                            "accessionNumber": ["0000950123-25-000001", "0000950123-25-000002"],
                            "primaryDocument": ["infotable.xml", "annual.htm"],
                            "primaryDocDescription": ["INFORMATION TABLE", "10-K"],
                        }
                    },
                },
            )
        if url.endswith("/infotable.xml"):
            return _FakeResponse(200, text=info_table_xml)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(sec_holdings, "_http_get", _fake_http_get)

    payload = sec_holdings.get_institutional_holdings("0001067983", quarter="2025Q1", limit=10)

    assert payload.get("error") is None
    assert payload.get("source") == "sec_13f"
    assert payload.get("cik") == "0001067983"
    assert payload.get("quarter") == "2025Q1"
    assert payload.get("regulatory_notes", {}).get("form_13f_due") == (
        "SEC Form 13F is due within 45 days after each calendar quarter end."
    )
    holdings = payload.get("holdings") or []
    assert [row.get("issuer_name") for row in holdings] == ["Apple Inc.", "NVIDIA Corp."]
    assert holdings[0]["ticker"] == "AAPL"
    assert holdings[0]["cusip"] == "037833100"
    assert holdings[0]["value_usd_thousands"] == 150000
    assert holdings[0]["shares"] == 1000
    assert holdings[0]["share_type"] == "SH"
    assert holdings[0]["voting_authority"]["sole"] == 1000


def test_get_insider_transactions_parses_form4_xml(monkeypatch):
    _reset_sec_cache()
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight admin@finsight.app")

    form4_xml = """<?xml version="1.0"?>
    <ownershipDocument>
      <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
        <issuerName>Apple Inc.</issuerName>
      </issuer>
      <reportingOwner>
        <reportingOwnerId>
          <rptOwnerCik>0001214156</rptOwnerCik>
          <rptOwnerName>Jane Officer</rptOwnerName>
        </reportingOwnerId>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <securityTitle><value>Common Stock</value></securityTitle>
          <transactionDate><value>2025-05-01</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>100</value></transactionShares>
            <transactionPricePerShare><value>185.5</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
          <postTransactionAmounts>
            <sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction>
          </postTransactionAmounts>
          <ownershipNature>
            <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
          </ownershipNature>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
      <derivativeTable>
        <derivativeTransaction>
          <securityTitle><value>Employee Stock Option</value></securityTitle>
          <transactionDate><value>2025-05-02</value></transactionDate>
          <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>50</value></transactionShares>
            <transactionPricePerShare><value>0</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
          <ownershipNature>
            <directOrIndirectOwnership><value>I</value></directOrIndirectOwnership>
          </ownershipNature>
        </derivativeTransaction>
      </derivativeTable>
    </ownershipDocument>
    """

    def _fake_http_get(url, **kwargs):
        if url.endswith("company_tickers.json"):
            return _FakeResponse(200, _ticker_map_payload())
        if "submissions/CIK0000320193.json" in url:
            return _FakeResponse(
                200,
                {
                    "name": "Apple Inc.",
                    "filings": {
                        "recent": {
                            "form": ["4", "8-K"],
                            "filingDate": ["2025-05-03", "2025-05-04"],
                            "reportDate": ["2025-05-02", "2025-05-04"],
                            "acceptanceDateTime": ["2025-05-03T12:00:00.000Z", "2025-05-04T12:00:00.000Z"],
                            "accessionNumber": ["0000320193-25-000004", "0000320193-25-000005"],
                            "primaryDocument": ["ownership.xml", "event.htm"],
                            "primaryDocDescription": ["FORM 4", "8-K"],
                        }
                    },
                },
            )
        if url.endswith("/ownership.xml"):
            return _FakeResponse(200, text=form4_xml)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(sec_holdings, "_http_get", _fake_http_get)

    payload = sec_holdings.get_insider_transactions("AAPL", days=180, limit=10)

    assert payload.get("error") is None
    assert payload.get("source") == "sec_form4"
    assert payload.get("regulatory_notes", {}).get("form_4_due") == (
        "In most cases, Form 4 is filed within two business days following the transaction date."
    )
    transactions = payload.get("transactions") or []
    assert len(transactions) == 2
    assert transactions[0]["transaction_code"] == "P"
    assert transactions[0]["acquired_disposed"] == "A"
    assert transactions[0]["shares"] == 100
    assert transactions[0]["price_per_share"] == 185.5
    assert transactions[0]["direct_or_indirect_ownership"] == "D"
    assert transactions[0]["interpretation_note"] == "Raw SEC Form 4 code P; do not infer intent from code alone."
    assert transactions[1]["security_type"] == "derivative"
    assert transactions[1]["transaction_code"] == "M"
    assert transactions[1]["acquired_disposed"] == "D"
    assert transactions[1]["direct_or_indirect_ownership"] == "I"


def test_get_holdings_overlap_compares_institution_holdings_to_portfolio(monkeypatch):
    _reset_sec_cache()
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight admin@finsight.app")

    info_table_xml = """<?xml version="1.0"?>
    <informationTable>
      <infoTable>
        <nameOfIssuer>Apple Inc.</nameOfIssuer>
        <cusip>037833100</cusip>
        <value>150000</value>
        <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
      <infoTable>
        <nameOfIssuer>NVIDIA Corp.</nameOfIssuer>
        <cusip>67066G104</cusip>
        <value>75000</value>
        <shrsOrPrnAmt><sshPrnamt>250</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
    </informationTable>
    """

    def _fake_http_get(url, **kwargs):
        if url.endswith("company_tickers.json"):
            return _FakeResponse(200, _ticker_map_payload())
        if "submissions/CIK0001067983.json" in url:
            return _FakeResponse(
                200,
                {
                    "filings": {
                        "recent": {
                            "form": ["13F-HR"],
                            "filingDate": ["2025-05-15"],
                            "reportDate": ["2025-03-31"],
                            "acceptanceDateTime": ["2025-05-15T12:00:00.000Z"],
                            "accessionNumber": ["0000950123-25-000001"],
                            "primaryDocument": ["infotable.xml"],
                            "primaryDocDescription": ["INFORMATION TABLE"],
                        }
                    }
                },
            )
        if url.endswith("/infotable.xml"):
            return _FakeResponse(200, text=info_table_xml)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(sec_holdings, "_http_get", _fake_http_get)

    payload = sec_holdings.get_holdings_overlap(
        positions=[
            {"ticker": "AAPL", "weight": 0.6},
            {"ticker": "MSFT", "weight": 0.4},
            {"symbol": "nvda", "shares": 10},
        ],
        holder_cik_or_name="0001067983",
        quarter="2025Q1",
    )

    assert payload.get("error") is None
    assert payload.get("portfolio_tickers") == ["AAPL", "MSFT", "NVDA"]
    assert payload.get("overlap_tickers") == ["AAPL", "NVDA"]
    assert payload.get("overlap_count") == 2
    assert payload.get("portfolio_only_tickers") == ["MSFT"]
    assert payload.get("institution_only_tickers") == []
