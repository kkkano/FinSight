# -*- coding: utf-8 -*-
"""P2-1 护城河前置：幻觉洗涤（事实核查）结果暴露到 report payload 的测试。

验证 build_report_payload 把 state.artifacts["verifier_result"] 转成
report["fact_check"] 结构，供前端 FactCheckCard 消费。
"""

from backend.graph.report_builder import build_report_payload


def _base_state(*, verifier_result=None):
    """构造最小可用的 investment_report state，可选注入 verifier_result。"""
    artifacts = {
        "draft_markdown": "## 投资研报：GOOG\n\n维持中性偏多。",
        "evidence_pool": [
            {
                "title": "GOOG fundamentals",
                "url": "https://example.com/goog-fundamentals",
                "snippet": "Revenue growth 11%, PE 28x, cloud margin improving.",
                "source": "example",
                "published_date": "2026-02-18T00:00:00Z",
                "confidence": 0.8,
            }
        ],
        "step_results": {},
        "errors": [],
        "render_vars": {
            "investment_summary": "基于当前估值与增长，维持中性偏多。",
            "conclusion": "结论偏中性，等待更多证据。",
        },
    }
    if verifier_result is not None:
        artifacts["verifier_result"] = verifier_result
    return {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["GOOG"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": artifacts,
        "trace": {},
    }


def test_fact_check_field_present_with_verifier_claims():
    """有验证器 claims 时，fact_check 字段携带真实 claims 与计数。"""
    state = _base_state(
        verifier_result={
            "enabled": True,
            "checked": True,
            "unsupported_claims": [
                {"claim": "Gemini 2.0 will launch in 2026Q2", "reason": "missing in evidence"},
                {"claim": "Revenue grew 50% YoY", "reason": "evidence shows 11%"},
            ],
        }
    )

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-fact-check-claims",
    )
    assert isinstance(report, dict)

    fact_check = report.get("fact_check")
    assert isinstance(fact_check, dict)
    assert fact_check.get("redaction_count") == 2
    assert fact_check.get("enabled") is True
    assert fact_check.get("checked") is True
    assert isinstance(fact_check.get("verified_at"), str) and fact_check.get("verified_at")

    claims = fact_check.get("verifier_claims")
    assert isinstance(claims, list) and len(claims) == 2
    assert claims[0]["claim"] == "Gemini 2.0 will launch in 2026Q2"
    assert claims[0]["reason"] == "missing in evidence"
    # 每条都必须有非空 reason（缺省时回退默认文案）
    assert all(item.get("claim") and item.get("reason") for item in claims)


def test_fact_check_redaction_count_zero_when_no_verifier_claims():
    """无验证器 claims（验证器没跑/没问题）时，redaction_count == 0。"""
    state = _base_state(
        verifier_result={
            "enabled": False,
            "checked": False,
            "unsupported_claims": [],
        }
    )

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-fact-check-zero",
    )
    assert isinstance(report, dict)

    fact_check = report.get("fact_check")
    assert isinstance(fact_check, dict)
    assert fact_check.get("redaction_count") == 0
    assert fact_check.get("verifier_claims") == []


def test_fact_check_field_present_even_without_verifier_result():
    """完全没有 verifier_result 时，仍构造 redaction_count==0 的 fact_check。

    这是护城河可见化的核心：零问题也要展示「全部通过」状态。
    """
    state = _base_state(verifier_result=None)

    report = build_report_payload(
        state=state,
        query="请做 GOOG 投资分析",
        thread_id="t-fact-check-missing",
    )
    assert isinstance(report, dict)

    fact_check = report.get("fact_check")
    assert isinstance(fact_check, dict)
    assert fact_check.get("redaction_count") == 0
    assert fact_check.get("verifier_claims") == []
    # 缺失验证器结果时 enabled/checked 应为 False
    assert fact_check.get("enabled") is False
    assert fact_check.get("checked") is False


def test_fact_check_truncates_claims_over_20():
    """claims 超过 20 条时截断到 20 条，redaction_count 同步为 20。"""
    many_claims = [
        {"claim": f"断言编号 {i}", "reason": f"原因 {i}"} for i in range(30)
    ]
    state = _base_state(
        verifier_result={
            "enabled": True,
            "checked": True,
            "unsupported_claims": many_claims,
        }
    )

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-fact-check-truncate",
    )
    assert isinstance(report, dict)

    fact_check = report.get("fact_check")
    assert isinstance(fact_check, dict)
    claims = fact_check.get("verifier_claims")
    assert isinstance(claims, list)
    assert len(claims) == 20
    assert fact_check.get("redaction_count") == 20
    # 截断保留前 20 条（顺序稳定）
    assert claims[0]["claim"] == "断言编号 0"
    assert claims[19]["claim"] == "断言编号 19"


def test_fact_check_skips_invalid_and_empty_claims():
    """非 dict 或 claim 为空的条目被跳过，只保留有效断言。"""
    state = _base_state(
        verifier_result={
            "enabled": True,
            "checked": True,
            "unsupported_claims": [
                {"claim": "有效断言", "reason": "有效原因"},
                {"claim": "", "reason": "空断言应被跳过"},
                "not a dict",
                {"reason": "缺 claim 字段"},
            ],
        }
    )

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-fact-check-invalid",
    )
    assert isinstance(report, dict)

    fact_check = report.get("fact_check")
    assert isinstance(fact_check, dict)
    claims = fact_check.get("verifier_claims")
    assert isinstance(claims, list) and len(claims) == 1
    assert claims[0]["claim"] == "有效断言"
    assert fact_check.get("redaction_count") == 1
