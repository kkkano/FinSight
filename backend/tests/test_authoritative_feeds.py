from backend.tools.authoritative_feeds import _extract_tickers


def test_authoritative_feed_ticker_extraction_ignores_title_case_common_words():
    assert _extract_tickers("Use sources for today's Fed news; never put internal tool errors in the answer.") == []
    assert _extract_tickers("I pasted a link, so fetch it before answering.") == []


def test_authoritative_feed_ticker_extraction_keeps_explicit_symbols():
    assert _extract_tickers("PLTR latest news with links") == ["PLTR"]
    assert _extract_tickers("AAPL and MSFT latest headlines") == ["AAPL", "MSFT"]
