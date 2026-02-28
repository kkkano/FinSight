from __future__ import annotations

from rag_qualityV2.engine_v2 import build_eval_report_v2, evaluate_case_v2
from rag_qualityV2.types_v2 import CaseResultV2, DriftResultV2, GateResultV2


class FakeChatClient:
    default_model = "fake-chat"

    def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> str:
        return "公司营收同比增长20%。毛利率提升至30%。"

    def complete_json(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> dict:
        if schema_name == "extract_keypoints":
            return {"keypoints": ["营收同比增长20%", "毛利率提升至30%"]}
        if schema_name == "extract_claims":
            return {"claims": ["营收同比增长20%", "毛利率提升至30%"]}
        if schema_name == "judge_claim":
            if "20%" in user_prompt or "30%" in user_prompt:
                return {
                    "label": "supported",
                    "is_numeric_claim": True,
                    "numeric_consistent": True,
                    "rationale": "ok",
                }
            return {
                "label": "unsupported",
                "is_numeric_claim": False,
                "numeric_consistent": False,
                "rationale": "no",
            }
        if schema_name == "judge_keypoint":
            return {"coverage": "covered", "context_supported": True, "rationale": "ok"}
        return {}


class FakeEmbedClient:
    default_model = "fake-embed"

    def embed_texts(self, texts: list[str], *, model: str | None = None, batch_size: int = 32) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * 8
            for i, ch in enumerate(t):
                vec[i % 8] += (ord(ch) % 31) / 31.0
            out.append(vec)
        return out


def test_evaluate_case_full_flow() -> None:
    chat = FakeChatClient()
    embed = FakeEmbedClient()
    metrics, artifacts, errors = evaluate_case_v2(
        case_id="c1",
        question="公司核心财务变化是什么？",
        ground_truth="营收同比增长20%，毛利率提升至30%。",
        answer="营收同比增长20%。毛利率提升至30%。",
        retrieved_contexts=["公司财报显示营收同比增长20%，毛利率提升至30%。"],
        chat_client=chat,
        embed_client=embed,
        embed_model=embed.default_model,
        mock_mode=False,
    )
    assert errors == {}
    assert artifacts["claim_count"] >= 1
    assert artifacts["keypoint_count"] >= 1
    for key, value in metrics.items():
        assert key in {
            "keypoint_coverage",
            "keypoint_context_recall",
            "claim_support_rate",
            "unsupported_claim_rate",
            "contradiction_rate",
            "numeric_consistency_rate",
        }
        if value is not None:
            assert 0.0 <= value <= 1.0


def test_build_report_schema() -> None:
    case = CaseResultV2(
        case_id="c1",
        doc_type="filing",
        question_type="factoid",
        answer_len=120,
        metrics={
            "keypoint_coverage": 0.8,
            "keypoint_context_recall": 0.85,
            "claim_support_rate": 0.8,
            "unsupported_claim_rate": 0.1,
            "contradiction_rate": 0.02,
            "numeric_consistency_rate": 0.95,
        },
    )
    report = build_eval_report_v2(
        layer="layer1_v2",
        dataset_version="v1",
        config={"mock_mode": True},
        case_results=[case],
        gate_result=GateResultV2(passed=True, failures=[]),
        drift_result=DriftResultV2(
            enabled=False,
            baseline_available=False,
            passed=True,
            deltas={},
            failures=[],
            baseline_run_id=None,
        ),
    )
    payload = report.to_dict()
    assert "run_id" in payload
    assert "overall_metrics" in payload
    assert "case_results" in payload
    assert payload["by_doc_type"]["filing"]["keypoint_coverage"] == 0.8
