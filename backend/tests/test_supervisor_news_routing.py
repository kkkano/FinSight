"""P0-9 Task5: NEWS 意图统一走舆情简报，二分法已废除"""
import pytest
from backend.orchestration.supervisor_agent import SupervisorAgent


def test_classify_news_subintent_removed():
    """fetch/analyze 二分法必须已删除"""
    assert not hasattr(SupervisorAgent, "_classify_news_subintent")


def test_handle_news_brief_exists():
    """统一入口 _handle_news_brief 必须存在"""
    assert hasattr(SupervisorAgent, "_handle_news_brief")


def test_old_handlers_removed():
    """旧的 _handle_news 已被 _handle_news_brief 取代"""
    assert not hasattr(SupervisorAgent, "_handle_news")


def test_market_news_brief_stub_exists():
    """无 ticker 路由桩 _handle_market_news_brief 必须存在（Task 6 完善）"""
    assert hasattr(SupervisorAgent, "_handle_market_news_brief")


def test_news_analysis_handler_preserved():
    """Selection Context 深度分析路径 _handle_news_analysis 必须原样保留"""
    assert hasattr(SupervisorAgent, "_handle_news_analysis")
