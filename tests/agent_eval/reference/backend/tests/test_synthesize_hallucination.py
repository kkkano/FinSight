# -*- coding: utf-8 -*-
from backend.graph.nodes.synthesize import (
    _HALLUCINATION_SAFE_PLACEHOLDER,
    _scrub_unverified_future_claims,
)


def test_scrub_unverified_future_claims_matches_b_style_statement():
    draft = "Gemini 1.5模型发布（2月底），将提升广告系统效果。"
    evidence = "当前证据仅包含估值与利润率数据，未提及具体发布时间。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert _HALLUCINATION_SAFE_PLACEHOLDER in out
    assert "Gemini 1.5模型发布（2月底）" not in out


def test_scrub_unverified_future_claims_matches_c_style_inverted_statement():
    draft = "（2026Q1）新处理器推出，并用于下一代端侧AI设备。"
    evidence = "证据池只包含历史财务数据，没有新品发布时间信息。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert _HALLUCINATION_SAFE_PLACEHOLDER in out
    assert "新处理器推出" not in out


def test_scrub_unverified_future_claims_keeps_month_phrase_when_grounded():
    draft = "Gemini 1.5模型发布（2月底），并上线到广告平台。"
    evidence = "公司公告：Gemini 1.5模型发布（2月底），并上线到广告平台。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert out == draft
    assert _HALLUCINATION_SAFE_PLACEHOLDER not in out


def test_scrub_unverified_future_claims_removes_unsupported_claim_but_keeps_other_text():
    draft = "核心观点：预计2026Q2发布Gemini 2.0。估值维持中性。"
    evidence = "当前仅有历史估值与现金流数据，未出现任何发布时间证据。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert _HALLUCINATION_SAFE_PLACEHOLDER in out
    assert "估值维持中性" in out


def test_scrub_unverified_future_claims_a_style_regression_guard():
    draft = "预计2026Q2发布Gemini 2.0并推动广告增长。"
    unsupported_evidence = "仅包含当前PE与增长率描述，未包含未来产品发布时间。"
    grounded_evidence = "公司公告指出：预计2026Q2发布Gemini 2.0并推动广告增长。"

    removed = _scrub_unverified_future_claims(draft, unsupported_evidence)
    kept = _scrub_unverified_future_claims(draft, grounded_evidence)

    assert _HALLUCINATION_SAFE_PLACEHOLDER in removed
    assert kept == draft
