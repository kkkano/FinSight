"""公司名的默认上市地不得覆盖用户明确指定的交易代码。"""
import pytest

from backend.config.ticker_mapping import extract_tickers


@pytest.mark.parametrize("query,expected", [
    ("分析腾讯控股（0700.HK）的最新财报、估值与主要风险。", ["0700.HK"]),
    ("Tencent (0700.HK) earnings and valuation", ["0700.HK"]),
    ("分析阿里巴巴（9988.HK）和腾讯控股（0700.HK）", ["9988.HK", "0700.HK"]),
    ("比较腾讯控股（0700.HK）与 TCEHY 的价格", ["0700.HK", "TCEHY"]),
    ("分析贵州茅台（600519.SH）", ["600519.SS"]),
    ("600519.SH 最新财报", ["600519.SS"]),
    ("分析腾讯的主要风险", ["TCEHY"]),
    ("腾讯（业务与竞争）", ["TCEHY"]),
])
def test_named_listing_uses_explicit_symbol_and_preserves_real_comparisons(query, expected):
    assert set(extract_tickers(query)["tickers"]) == set(expected)


@pytest.mark.asyncio
async def test_hong_kong_query_compiles_to_one_subject():
    from backend.graph.nodes.route_request import route_request
    result = await route_request({"query": "分析腾讯控股（0700.HK）的最新财报、估值与主要风险。",
                                  "output_mode": "chat", "ui_context": {}})
    assert result["subject"]["tickers"] == ["0700.HK"]
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["tickers"] == ["0700.HK"]
