# -*- coding: utf-8 -*-

from backend.config.ticker_mapping import extract_tickers, is_probably_ticker


def test_is_probably_ticker_accepts_cn_market_suffix_symbol():
    assert is_probably_ticker("600519.SS")
    assert is_probably_ticker("000001.SZ")


def test_extract_tickers_keeps_cn_market_suffix_symbol():
    meta = extract_tickers("请分析 600519.SS 的估值与风险")
    tickers = meta.get("tickers") if isinstance(meta, dict) else []
    assert "600519.SS" in tickers
    assert "SS" not in tickers


def test_ascii_aliases_do_not_match_inside_url_or_words():
    meta = extract_tickers(
        "Read https://example.com/msft-rates and tell me whether it matters for MSFT."
    )

    assert meta["tickers"] == ["MSFT"]
    assert "ETH-USD" not in meta["tickers"]
    assert "eth" not in meta["company_names"]


def test_crypto_alias_still_matches_as_standalone_token():
    meta = extract_tickers("Compare ETH with BTC quickly.")

    assert meta["tickers"] == ["ETH-USD", "BTC-USD"]
