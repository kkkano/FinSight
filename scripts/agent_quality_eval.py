# -*- coding: utf-8 -*-
"""Deterministic eval gate for single-agent research quality.

This script intentionally runs agents against local fixtures instead of live
market APIs. It gives us a repeatable before/after signal while strengthening
agent internals.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _EvalCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        del ttl
        self._store[key] = value


class _FixtureTools:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    def get_financial_statements(self, ticker: str) -> dict[str, Any]:
        del ticker
        payload = self.fixture.get("financials")
        return payload if isinstance(payload, dict) else {"error": "missing_fixture_financials"}

    def get_company_info(self, ticker: str) -> str:
        del ticker
        return str(self.fixture.get("company_info") or "")

    def get_earnings_estimates(self, ticker: str) -> dict[str, Any]:
        del ticker
        payload = self.fixture.get("earnings_estimates")
        return payload if isinstance(payload, dict) else {"error": "missing_fixture_earnings"}

    def get_eps_revisions(self, ticker: str) -> dict[str, Any]:
        del ticker
        payload = self.fixture.get("eps_revisions")
        return payload if isinstance(payload, dict) else {"error": "missing_fixture_eps_revisions"}

    def get_company_news(self, ticker: str) -> list[dict[str, Any]]:
        del ticker
        news = self.fixture.get("news")
        return [dict(item) for item in news] if isinstance(news, list) else []

    def get_event_calendar(self, ticker: str, days_ahead: int = 30) -> dict[str, Any]:
        del ticker, days_ahead
        payload = self.fixture.get("event_calendar")
        return payload if isinstance(payload, dict) else {}

    def score_news_source_reliability(self, source: str = "", url: str = "") -> dict[str, Any]:
        text = f"{source} {url}".lower()
        if any(domain in text for domain in ("reuters", "sec.gov", "bloomberg", "wsj", "ft.com")):
            return {"reliability_score": 0.9, "reliability_tier": "high", "reason": "fixture_authoritative"}
        if "yahoo" in text or "marketwatch" in text or "nasdaq" in text:
            return {"reliability_score": 0.78, "reliability_tier": "medium", "reason": "fixture_market_media"}
        return {"reliability_score": 0.6, "reliability_tier": "medium", "reason": "fixture_default"}

    def get_stock_price(self, ticker: str) -> dict[str, Any]:
        del ticker
        payload = self.fixture.get("quote")
        return payload if isinstance(payload, dict) else {"price": None, "change_percent": None}

    def get_factor_exposure(self, positions: list[dict[str, Any]], lookback_days: int = 252) -> dict[str, Any]:
        del positions, lookback_days
        payload = self.fixture.get("factor_exposure")
        return payload if isinstance(payload, dict) else {"error": "missing_fixture_factor_exposure"}

    def run_portfolio_stress_test(self, positions: list[dict[str, Any]], lookback_days: int = 252) -> dict[str, Any]:
        del positions, lookback_days
        payload = self.fixture.get("stress_test")
        return payload if isinstance(payload, dict) else {"error": "missing_fixture_stress_test"}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _expected_statuses(value: Any) -> set[str]:
    if isinstance(value, str):
        cleaned = value.strip().lower()
        return {cleaned} if cleaned else set()
    if isinstance(value, list):
        return {str(item or "").strip().lower() for item in value if str(item or "").strip()}
    return set()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list):
        raise ValueError(f"dataset must be a list or object with cases: {path}")

    result: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        if not str(item.get("id") or "").strip():
            raise ValueError("every eval case requires id")
        if not str(item.get("agent") or "").strip():
            raise ValueError(f"eval case requires agent: {item.get('id')}")
        result.append(item)
    return result


def _build_agent(agent_name: str, fixture: dict[str, Any]) -> Any:
    tools = _FixtureTools(fixture)
    cache = _EvalCache()
    normalized = str(agent_name or "").strip().lower()
    if normalized == "fundamental":
        from backend.agents.fundamental_agent import FundamentalAgent

        return FundamentalAgent(llm=None, cache=cache, tools_module=tools)
    if normalized == "news":
        from backend.agents.news_agent import NewsAgent

        return NewsAgent(llm=None, cache=cache, tools_module=tools)
    if normalized == "risk_agent":
        from backend.agents.risk_agent import RiskAgent

        return RiskAgent(llm=None, cache=cache, tools_module=tools)
    raise ValueError(f"unsupported agent in eval dataset: {agent_name}")


async def _run_case(case: dict[str, Any]) -> Any:
    agent = _build_agent(str(case.get("agent") or ""), case.get("fixture") if isinstance(case.get("fixture"), dict) else {})
    return await agent.research(
        query=str(case.get("query") or ""),
        ticker=str(case.get("ticker") or ""),
    )


def _collect_output_metrics(output: Any) -> dict[str, Any]:
    evidence = _as_list(getattr(output, "evidence", []))
    claims = _as_list(getattr(output, "claims", []))
    risks = _as_list(getattr(output, "risks", []))
    data_sources = _as_list(getattr(output, "data_sources", []))
    evidence_quality = getattr(output, "evidence_quality", {})
    agent_quality = evidence_quality.get("agent_quality") if isinstance(evidence_quality, dict) else {}
    agent_quality = agent_quality if isinstance(agent_quality, dict) else {}
    agent_quality_status = str(agent_quality.get("status") or "missing").strip().lower()
    self_check = evidence_quality.get("agent_self_check") if isinstance(evidence_quality, dict) else {}
    self_check = self_check if isinstance(self_check, dict) else {}
    self_check_status = str(self_check.get("status") or "missing").strip().lower()
    self_check_gaps = _as_list(self_check.get("gaps"))
    evidence_source_ids = {
        str(getattr(item, "meta", {}).get("source_id") or "").strip()
        for item in evidence
        if isinstance(getattr(item, "meta", None), dict)
        and str(getattr(item, "meta", {}).get("source_id") or "").strip()
    }

    sourced_claims = 0
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        sources = claim.get("evidence_ids") or claim.get("sources") or claim.get("evidence") or claim.get("source")
        source_ids = [str(item).strip() for item in sources] if isinstance(sources, list) else [str(sources).strip()]
        source_ids = [item for item in source_ids if item]
        if source_ids and (not evidence_source_ids or evidence_source_ids.intersection(source_ids)):
            sourced_claims += 1

    claim_source_ratio = (sourced_claims / len(claims)) if claims else 0.0
    evidence_with_url = [
        item for item in evidence
        if getattr(item, "url", None) or (isinstance(getattr(item, "meta", None), dict) and getattr(item, "meta", {}).get("url"))
    ]

    return {
        "evidence_count": len(evidence),
        "evidence_with_url_count": len(evidence_with_url),
        "source_count": len({str(source) for source in data_sources if str(source or "").strip()}),
        "claim_count": len(claims),
        "claim_source_ratio": round(claim_source_ratio, 4),
        "risk_count": len(risks),
        "confidence": round(_safe_float(getattr(output, "confidence", 0.0)), 4),
        "fallback_used": bool(getattr(output, "fallback_used", False)),
        "agent_quality_status": agent_quality_status,
        "self_check_status": self_check_status,
        "self_check_gap_count": len(self_check_gaps),
        "self_check_pass": 1.0 if self_check_status == "pass" else 0.0,
    }


def _grade_case(case: dict[str, Any], output: Any) -> dict[str, Any]:
    metrics = _collect_output_metrics(output)
    expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    issues: list[str] = []

    min_evidence = int(expect.get("min_evidence_count") or 0)
    if metrics["evidence_count"] < min_evidence:
        issues.append(f"evidence_count {metrics['evidence_count']} < {min_evidence}")

    min_risk = int(expect.get("min_risk_count") or 0)
    if metrics["risk_count"] < min_risk:
        issues.append(f"risk_count {metrics['risk_count']} < {min_risk}")

    min_claims = int(expect.get("min_claim_count") or 0)
    if metrics["claim_count"] < min_claims:
        issues.append(f"claim_count {metrics['claim_count']} < {min_claims}")

    min_claim_source_ratio = expect.get("min_claim_source_ratio")
    if min_claim_source_ratio is not None:
        threshold = _safe_float(min_claim_source_ratio)
        if _safe_float(metrics.get("claim_source_ratio")) < threshold:
            issues.append(f"claim_source_ratio {metrics['claim_source_ratio']} < {threshold}")

    required_quality_statuses = _expected_statuses(expect.get("require_agent_quality_status"))
    actual_quality_status = str(metrics.get("agent_quality_status") or "").strip().lower()
    if required_quality_statuses and actual_quality_status not in required_quality_statuses:
        issues.append(f"agent_quality_status {metrics['agent_quality_status']} not in {sorted(required_quality_statuses)}")

    required_self_check_statuses = _expected_statuses(expect.get("require_self_check_status"))
    actual_self_check_status = str(metrics.get("self_check_status") or "").strip().lower()
    if required_self_check_statuses and actual_self_check_status not in required_self_check_statuses:
        issues.append(f"self_check_status {metrics['self_check_status']} not in {sorted(required_self_check_statuses)}")

    return {
        "id": case.get("id"),
        "agent": case.get("agent"),
        "ticker": case.get("ticker"),
        "query": case.get("query"),
        "verdict": "PASS" if not issues else "FAIL",
        "metrics": metrics,
        "issues": issues,
        "output": {
            "agent_name": getattr(output, "agent_name", None),
            "summary": getattr(output, "summary", ""),
            "claims": _jsonable(getattr(output, "claims", [])),
            "risks": _jsonable(getattr(output, "risks", [])),
            "evidence": _jsonable(getattr(output, "evidence", [])),
            "evidence_quality": _jsonable(getattr(output, "evidence_quality", {})),
            "trace": _jsonable(getattr(output, "trace", [])),
        },
    }


def _average_metric(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    values = [_safe_float((row.get("metrics") or {}).get(key)) for row in rows]
    return round(sum(values) / len(values), 4)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pass_count = sum(1 for row in rows if row.get("verdict") == "PASS")
    fail_count = len(rows) - pass_count
    metric_keys = [
        "evidence_count",
        "evidence_with_url_count",
        "source_count",
        "claim_count",
        "claim_source_ratio",
        "risk_count",
        "confidence",
        "agent_quality_status",
        "self_check_gap_count",
        "self_check_pass",
    ]
    averages = {key: _average_metric(rows, key) for key in metric_keys if key != "agent_quality_status"}
    averages["self_check_pass_rate"] = averages.get("self_check_pass", 0.0)
    return {
        "case_count": len(rows),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "agent_averages": averages,
    }


def evaluate_cases(cases: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        output = asyncio.run(_run_case(case))
        rows.append(_grade_case(case, output))

    return {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": _summarize(rows),
        "cases": rows,
    }


def compare_runs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_metrics = ((before.get("summary") or {}).get("agent_averages") or {}) if isinstance(before, dict) else {}
    after_metrics = ((after.get("summary") or {}).get("agent_averages") or {}) if isinstance(after, dict) else {}
    keys = sorted(set(before_metrics) | set(after_metrics))
    deltas = {
        key: round(_safe_float(after_metrics.get(key)) - _safe_float(before_metrics.get(key)), 4)
        for key in keys
    }
    fail_count = int(((after.get("summary") or {}).get("fail_count") or 0)) if isinstance(after, dict) else 0
    regressed = [
        key for key, value in deltas.items()
        if key in {"evidence_count", "claim_count", "claim_source_ratio", "risk_count", "confidence"} and value < 0
    ]
    verdict = "PASS" if fail_count == 0 and not regressed else "FAIL"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict,
        "deltas": deltas,
        "regressed_metrics": regressed,
        "before_run_id": before.get("run_id") if isinstance(before, dict) else None,
        "after_run_id": after.get("run_id") if isinstance(after, dict) else None,
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/eval/agent_quality_cases.json")
    parser.add_argument("--run-id", default="local-agent-quality")
    parser.add_argument("--out", default="tmp/agent_quality_eval.json")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    if args.compare:
        before_path = Path(args.compare[0])
        after_path = Path(args.compare[1])
        if not before_path.is_absolute():
            before_path = ROOT / before_path
        if not after_path.is_absolute():
            after_path = ROOT / after_path
        result = compare_runs(_load_json(before_path), _load_json(after_path))
        _write_json(out_path, result)
        print(f"[agent-quality-compare] {result['verdict']}; wrote {out_path.relative_to(ROOT)}")
        if result["verdict"] != "PASS":
            raise SystemExit(1)
        return

    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = ROOT / dataset
    cases = load_cases(dataset)
    result = evaluate_cases(cases, run_id=str(args.run_id or "local-agent-quality"))
    _write_json(out_path, result)

    summary = result["summary"]
    print(
        f"[agent-quality-eval] {summary['pass_count']} PASS, {summary['fail_count']} FAIL "
        f"across {summary['case_count']} cases; wrote {out_path.relative_to(ROOT)}"
    )
    for row in result["cases"]:
        print(f"- {row['id']}: {row['verdict']}")
        for issue in row["issues"]:
            print(f"  - {issue}")
    if summary["fail_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
