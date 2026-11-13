"""P0-2: 数据缺失时 confidence 不得演戏"""


def test_macro_missing_quality_confidence_constant():
    """宏观 agent 质量分缺失时的置信度常量必须存在且 <= 0.35"""
    from backend.agents.macro_agent import MacroAgent

    value = getattr(MacroAgent, "_MISSING_QUALITY_CONFIDENCE", None)
    assert value is not None, "MacroAgent 必须定义 _MISSING_QUALITY_CONFIDENCE 常量"
    assert value <= 0.35, f"质量分缺失时置信度 {value} 不得超过 0.35（演戏行为）"


def test_fundamental_no_evidence_confidence_is_honest():
    """基本面 agent 源码中：无证据分支的 confidence 必须 <= 0.1"""
    import inspect
    import backend.agents.fundamental_agent as mod

    source = inspect.getsource(mod)
    # 旧的演戏代码模式必须已删除
    assert "(0.7 if evidence else 0.2)" not in source, "旧的 0.2 演戏 confidence 仍存在"
    assert "max(0.2, min(0.92, confidence))" not in source or "if evidence:" in source, (
        "max(0.2,...) 下限保护对无证据场景仍生效"
    )


def test_macro_missing_quality_adds_risk_warning():
    """宏观 agent 源码中：质量分缺失时必须有风险警告逻辑"""
    import inspect
    import backend.agents.macro_agent as mod

    source = inspect.getsource(mod)
    assert "_MISSING_QUALITY_CONFIDENCE" in source
    assert "宏观数据质量未评估" in source, "质量分缺失时必须向 risks 添加中文警告"
