"""P0-1: FRED 无 API key 时不得返回编造的宏观数据"""
import backend.tools.macro as macro_tools


def test_get_fred_data_without_key_returns_unavailable(monkeypatch):
    """无 FRED_API_KEY 时必须返回 data_unavailable，禁止返回编造值"""
    # FRED_API_KEY 是 macro.py 的模块级常量（macro.py:99 `api_key = FRED_API_KEY`）
    monkeypatch.setattr(macro_tools, "FRED_API_KEY", "")

    result = macro_tools.get_fred_data()

    # 绝不允许出现编造的数值（3.0 / 4.5 / 4.0）
    assert result.get("cpi") is None
    assert result.get("fed_rate") is None
    assert result.get("unemployment") is None
    # 状态必须从 "success" 变为 "data_unavailable"
    assert result.get("status") == "data_unavailable"
    assert "FRED_API_KEY" in str(result.get("unavailable_reason", ""))


def test_get_fred_data_without_key_no_estimate_source(monkeypatch):
    """无 key 时不得使用 source=estimate 伪装"""
    monkeypatch.setattr(macro_tools, "FRED_API_KEY", "")

    result = macro_tools.get_fred_data()
    assert result.get("source") != "estimate"
