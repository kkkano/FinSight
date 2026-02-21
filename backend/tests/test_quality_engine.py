# -*- coding: utf-8 -*-
from backend.report.quality_engine import (
    apply_quality_to_report,
    build_runtime_quality_reasons,
    evaluate_runtime_report_quality,
)


def test_apply_quality_to_report_writes_top_level_and_meta():
    report = {
        "report_id": "rpt-test",
        "meta": {},
        "report_quality": {
            "state": "warn",
            "reasons": [
                {
                    "code": "TEST_WARN",
                    "severity": "warn",
                    "metric": "x",
                    "actual": 1,
                    "threshold": 0,
                    "message": "warn",
                }
            ],
        },
    }
    quality, blocked = apply_quality_to_report(report)
    assert blocked is False
    assert quality.get("state") == "warn"
    assert isinstance(report.get("report_quality"), dict)
    assert isinstance((report.get("meta") or {}).get("report_quality"), dict)


def test_runtime_quality_thresholds_can_be_overridden(monkeypatch):
    monkeypatch.setenv("REPORT_QUALITY_GROUNDING_BLOCK", "0.5")
    monkeypatch.setenv("REPORT_QUALITY_GROUNDING_WARN", "0.8")
    monkeypatch.setenv("REPORT_QUALITY_VERIFIER_BLOCK_COUNT", "4")
    monkeypatch.setenv("REPORT_QUALITY_VERIFIER_WARN_COUNT", "2")

    reasons = build_runtime_quality_reasons(
        quality_hints={"deep_report_required": True, "missing_counts": {"critical": 0, "important": 0, "minor": 0}},
        grounding_stats={"grounding_rate": 0.55},
        verifier_claims=[{"claim": "a"}, {"claim": "b"}, {"claim": "c"}],
    )
    codes = {item.get("code") for item in reasons}
    # 0.55 >= 0.5 -> no block, but < 0.8 -> warn
    assert "GROUNDING_RATE_WARN" in codes
    assert "GROUNDING_RATE_BELOW_MIN" not in codes
    # verifier_count=3, block threshold=4, warn threshold=2 -> warn only
    assert "VERIFIER_UNSUPPORTED_CLAIMS_WARN" in codes
    assert "VERIFIER_UNSUPPORTED_CLAIMS_BLOCK" not in codes


def test_evaluate_runtime_quality_merges_with_existing_quality():
    merged = evaluate_runtime_report_quality(
        existing_quality={
            "state": "warn",
            "reasons": [
                {
                    "code": "EXISTING_WARN",
                    "severity": "warn",
                    "metric": "existing",
                    "actual": 1,
                    "threshold": 0,
                    "message": "existing warn",
                }
            ],
        },
        quality_hints={
            "deep_report_required": True,
            "missing_counts": {"critical": 1, "important": 0, "minor": 0},
            "missing_requirements": ["10-K"],
        },
        grounding_stats={"grounding_rate": 0.4},
        verifier_claims=[],
    )
    assert merged.get("state") == "block"
    reasons = merged.get("reasons") or []
    codes = {item.get("code") for item in reasons if isinstance(item, dict)}
    assert "EXISTING_WARN" in codes
    assert "QUALITY_PROFILE_CRITICAL_MISSING" in codes
    assert "GROUNDING_RATE_BELOW_MIN" in codes
