"""P0-9 Task1: 新闻条目来源不得重复显示"""
from backend.tools.news import _format_headline_line, _strip_trailing_source


def test_strip_trailing_source_with_dash():
    assert _strip_trailing_source("Apple Rises 5% - Yahoo Finance", "Yahoo Finance") == "Apple Rises 5%"


def test_strip_trailing_source_with_pipe():
    assert _strip_trailing_source("Apple Q2 Earnings Beat | Bloomberg", "Bloomberg") == "Apple Q2 Earnings Beat"


def test_strip_trailing_source_no_match_keeps_title():
    assert _strip_trailing_source("Apple Rises - strong demand", "Reuters") == "Apple Rises - strong demand"


def test_strip_trailing_source_case_insensitive():
    assert _strip_trailing_source("Apple Rises - REUTERS", "Reuters") == "Apple Rises"


def test_format_headline_line_no_duplicate_source():
    line = _format_headline_line(
        date_str="2026-06-01",
        title="Apple Q2 Earnings Beat Expectations - Reuters",
        source="Reuters",
        url="https://example.com/a",
    )
    # 来源 "Reuters" 在整行中只能出现一次
    assert line.count("Reuters") == 1


def test_format_headline_line_unified_format():
    line = _format_headline_line(
        date_str="2026-06-01",
        title="Apple Rises",
        source="Reuters",
        url="https://example.com/a",
    )
    # 新格式：[标题](url) — 来源 · 日期
    assert "[Apple Rises](https://example.com/a)" in line
    assert "— Reuters" in line
    assert "2026-06-01" in line
