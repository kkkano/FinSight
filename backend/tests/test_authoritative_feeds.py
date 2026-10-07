from backend.tools.authoritative_feeds import _extract_tickers


def test_company_query_does_not_match_unrelated_global_feed():
    import backend.tools.authoritative_feeds as feeds
    item = {"title": "Inflation outlook rises to 3.9%", "snippet": "Heating oil prices rise in the Northeast", "url": "https://www.reuters.com/world/markets"}
    assert not feeds._matches_query(item, feeds._query_tokens("游族网络 请给我一份游族网络的投研分析报告"))


def test_authoritative_feed_ticker_extraction_ignores_title_case_common_words():
    assert _extract_tickers("Use sources for today's Fed news; never put internal tool errors in the answer.") == []
    assert _extract_tickers("I pasted a link, so fetch it before answering.") == []


def test_authoritative_feed_ticker_extraction_keeps_explicit_symbols():
    assert _extract_tickers("PLTR latest news with links") == ["PLTR"]
    assert _extract_tickers("AAPL and MSFT latest headlines") == ["AAPL", "MSFT"]
