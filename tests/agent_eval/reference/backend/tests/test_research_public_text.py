"""内部窗口字段应表达为用户能理解的限制，不进入投资研究正文。"""
from backend.graph.renderers.research_report import _public_text


def test_window_and_provider_metadata_become_plain_language():
    raw='未来90天（direction=future、days_ahead=90）的事件status=scheduled、verification=provider_reported；coverage_window.exhaustive=false（C2）。'
    displayed=_public_text(raw)
    assert '未来90天' in displayed and '已排期' in displayed
    assert '尚未获官方确认' in displayed and '并非完整事件清单' in displayed
    assert all(word not in displayed for word in ('direction=', 'days_ahead=', 'status=', 'verification=', 'exhaustive=', 'C2'))
    assert 'coverage_window.exhaustive=false' in raw


def test_inline_local_reference_groups_do_not_replace_financial_numbers():
    raw='2026-10-08除息，金额1.5 USD（E7、E15）；RSI(14)为56.59，C2单元格仅是原文描述。'
    displayed=_public_text(raw)
    assert 'E7' not in displayed and 'E15' not in displayed
    assert all(value in displayed for value in ('2026-10-08','1.5 USD','RSI(14)','56.59','C2单元格'))
