"""P0-5: CN/HK 市场筛选不得静默降级为美股热门列表"""
from backend.tools.screener import _yfinance_screen_stocks


def test_cn_market_fallback_returns_explicit_error():
    """CN 市场降级时必须返回明确错误，不得返回美股列表"""
    result = _yfinance_screen_stocks("CN", {}, 20, "marketCap", "desc")

    assert result.get("success") is False
    error_text = str(result.get("error", ""))
    assert "CN" in error_text or "A股" in error_text
    assert not result.get("items"), "CN 降级时不得返回任何（美股）条目"


def test_hk_market_fallback_returns_explicit_error():
    result = _yfinance_screen_stocks("HK", {}, 20, "marketCap", "desc")
    assert result.get("success") is False
    assert not result.get("items")


def test_cn_fallback_has_chinese_capability_note():
    """CN 降级的 capability_note 必须是中文且明确说明"""
    result = _yfinance_screen_stocks("CN", {}, 20, "marketCap", "desc")
    note = str(result.get("capability_note", ""))
    assert "筛选" in note  # 中文说明


def test_us_market_fallback_marks_popular_stocks(monkeypatch):
    """US 市场降级到热门股仍允许，但 capability_note 必须明确标注这不是筛选结果"""
    # mock yfinance 避免真实网络调用
    import backend.tools.screener as screener_mod

    def fake_popular(market, filters, limit, sort_by, sort_order):
        return {
            "success": True,
            "market": market,
            "items": [{"symbol": "AAPL", "name": "Apple", "price": 200.0, "market_cap": 3e12}],
            "count": 1,
            "source": "yfinance_popular",
            "capability_note": "Using popular US stocks (FMP unavailable)",
        }

    monkeypatch.setattr(screener_mod, "_yfinance_popular_stocks", fake_popular)
    result = _yfinance_screen_stocks("US", {}, 5, "marketCap", "desc")

    assert result.get("success") is True
    note = str(result.get("capability_note", ""))
    # 中文明确标注"非筛选结果"
    assert "非筛选结果" in note or "热门" in note
