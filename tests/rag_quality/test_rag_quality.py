"""
RAG 生成质量评估 - pytest 快速测试套件

原则：
- 所有测试均为纯数据/逻辑验证，不调用真实 LLM 或向量数据库
- 目标运行时间 < 500ms，适合 CI pre-commit 阶段

真实 RAGAS 评估（需要 LLM API）请使用：
    python tests/rag_quality/run_rag_quality.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# conftest.py 中定义了所有 fixtures，此处直接使用

EVAL_DIR = Path(__file__).parent
REQUIRED_CASE_FIELDS = {"id", "doc_type", "question", "ground_truth", "mock_contexts"}
VALID_DOC_TYPES = {"filing", "transcript", "news"}
REQUIRED_METRIC_KEYS = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}


# ── 1. 数据集结构校验 ────────────────────────────────────────────────────────

class TestDatasetStructure:
    """确保黄金数据集格式正确，是所有评估的基础。"""

    def test_dataset_file_exists(self) -> None:
        assert (EVAL_DIR / "dataset.json").exists(), "dataset.json 不存在，无法运行评估"

    def test_dataset_has_version(self, dataset: dict[str, Any]) -> None:
        assert "version" in dataset, "数据集缺少 version 字段"

    def test_dataset_has_cases(self, dataset: dict[str, Any]) -> None:
        assert "cases" in dataset, "数据集缺少 cases 字段"
        assert len(dataset["cases"]) > 0, "cases 列表为空"

    def test_each_case_has_required_fields(self, dataset_cases: list[dict[str, Any]]) -> None:
        for case in dataset_cases:
            missing = REQUIRED_CASE_FIELDS - set(case.keys())
            assert not missing, f"案例 {case.get('id', '?')} 缺少字段: {missing}"

    def test_doc_types_all_valid(self, dataset_cases: list[dict[str, Any]]) -> None:
        for case in dataset_cases:
            assert case["doc_type"] in VALID_DOC_TYPES, (
                f"案例 {case['id']} 的 doc_type={case['doc_type']} 不合法，"
                f"必须是 {VALID_DOC_TYPES} 之一"
            )

    def test_covers_all_three_doc_types(self, dataset_cases: list[dict[str, Any]]) -> None:
        """必须覆盖 filing / transcript / news 三类，否则评估不完整。"""
        actual_types = {c["doc_type"] for c in dataset_cases}
        assert actual_types == VALID_DOC_TYPES, (
            f"数据集未覆盖所有文档类型。已有: {actual_types}，缺少: {VALID_DOC_TYPES - actual_types}"
        )

    def test_case_ids_are_unique(self, dataset_cases: list[dict[str, Any]]) -> None:
        ids = [c["id"] for c in dataset_cases]
        assert len(ids) == len(set(ids)), f"存在重复案例 ID: {[i for i in ids if ids.count(i) > 1]}"

    def test_mock_contexts_non_empty(self, dataset_cases: list[dict[str, Any]]) -> None:
        for case in dataset_cases:
            ctxs = case["mock_contexts"]
            assert isinstance(ctxs, list) and len(ctxs) >= 1, (
                f"案例 {case['id']} 的 mock_contexts 为空，无法做 context 相关指标评估"
            )
            for ctx in ctxs:
                assert isinstance(ctx, str) and ctx.strip(), (
                    f"案例 {case['id']} 存在空 context 字符串"
                )

    def test_ground_truth_non_empty(self, dataset_cases: list[dict[str, Any]]) -> None:
        for case in dataset_cases:
            gt = case.get("ground_truth", "")
            assert isinstance(gt, str) and len(gt.strip()) > 10, (
                f"案例 {case['id']} 的 ground_truth 过短或为空（最少10字符），"
                "context_recall 评估需要完整的参考答案"
            )

    def test_questions_non_empty(self, dataset_cases: list[dict[str, Any]]) -> None:
        for case in dataset_cases:
            q = case.get("question", "")
            assert isinstance(q, str) and q.strip().endswith("？"), (
                f"案例 {case['id']} 的 question 为空或不以问号结尾"
            )


# ── 2. 阈值配置校验 ──────────────────────────────────────────────────────────

class TestThresholdsConfig:
    """确保阈值配置文件格式正确，门控逻辑可以正常运行。"""

    def test_thresholds_file_exists(self) -> None:
        assert (EVAL_DIR / "thresholds.json").exists(), "thresholds.json 不存在"

    def test_all_metric_keys_present(self, thresholds: dict[str, Any]) -> None:
        metric_cfg = thresholds.get("metrics", {})
        missing = REQUIRED_METRIC_KEYS - set(metric_cfg.keys())
        assert not missing, f"thresholds.json 缺少指标配置: {missing}"

    def test_min_values_in_valid_range(self, thresholds: dict[str, Any]) -> None:
        for key, cfg in thresholds["metrics"].items():
            min_val = cfg["min"]
            assert 0.0 <= min_val <= 1.0, (
                f"指标 {key} 的 min={min_val} 不在 [0, 1] 范围内"
            )

    def test_excellent_greater_than_min(self, thresholds: dict[str, Any]) -> None:
        for key, cfg in thresholds["metrics"].items():
            if "excellent" in cfg:
                assert cfg["excellent"] > cfg["min"], (
                    f"指标 {key} 的 excellent={cfg['excellent']} 应大于 min={cfg['min']}"
                )

    def test_drift_gates_present(self, thresholds: dict[str, Any]) -> None:
        drift = thresholds.get("drift_gates", {})
        for key in REQUIRED_METRIC_KEYS:
            assert f"{key}_delta_min" in drift, f"drift_gates 缺少 {key}_delta_min"

    def test_drift_values_are_negative(self, thresholds: dict[str, Any]) -> None:
        """漂移容忍值应为负数，表示允许一定程度的退步。"""
        for key, val in thresholds["drift_gates"].items():
            assert val <= 0, f"{key}={val} 应 <= 0（表示允许退步幅度）"

    def test_doc_type_overrides_valid(self, thresholds: dict[str, Any]) -> None:
        overrides = thresholds.get("doc_type_overrides", {})
        for doc_type, override in overrides.items():
            assert doc_type in VALID_DOC_TYPES, f"override 中有未知 doc_type: {doc_type}"
            for metric_key, metric_cfg in override.items():
                if metric_key == "description":
                    continue
                assert metric_key in REQUIRED_METRIC_KEYS, (
                    f"doc_type_overrides.{doc_type} 中有未知指标: {metric_key}"
                )
                if "min" in metric_cfg:
                    assert 0.0 <= metric_cfg["min"] <= 1.0


# ── 3. 门控逻辑单元测试 ──────────────────────────────────────────────────────

class TestGateCheckerLogic:
    """验证门控判断逻辑本身的正确性（不依赖真实 RAGAS 结果）。"""

    def test_passing_metrics_no_failures(
        self,
        gate_checker,
        passing_metrics: dict[str, float],
    ) -> None:
        failures = gate_checker(passing_metrics)
        assert failures == [], f"合格指标不应触发门控，但触发了: {failures}"

    def test_failing_metrics_detected(
        self,
        gate_checker,
        failing_metrics: dict[str, float],
    ) -> None:
        failures = gate_checker(failing_metrics)
        assert len(failures) > 0, "低于阈值的指标应被门控拦截"

    def test_identifies_exactly_which_metrics_fail(
        self,
        gate_checker,
        failing_metrics: dict[str, float],
    ) -> None:
        """精确定位到 faithfulness 和 context_recall 失败。"""
        failures = gate_checker(failing_metrics)
        failure_keys = [f.split(":")[0] for f in failures]
        assert "faithfulness" in failure_keys, "faithfulness=0.72 应低于 min=0.80"
        assert "context_recall" in failure_keys, "context_recall=0.65 应低于 min=0.70"
        assert "answer_relevancy" not in failure_keys, "answer_relevancy=0.80 不应触发失败"

    def test_missing_metric_is_flagged(self, gate_checker) -> None:
        incomplete = {"faithfulness": 0.85}  # 缺少其他三项
        failures = gate_checker(incomplete)
        failure_keys = [f.split(":")[0] for f in failures]
        assert "answer_relevancy" in failure_keys
        assert "context_precision" in failure_keys
        assert "context_recall" in failure_keys

    def test_boundary_value_passes(self, gate_checker, thresholds: dict[str, Any]) -> None:
        """恰好等于 min 阈值时应通过门控（>=，非 >）。"""
        boundary = {k: thresholds["metrics"][k]["min"] for k in REQUIRED_METRIC_KEYS}
        failures = gate_checker(boundary)
        assert failures == [], f"边界值 {boundary} 应通过，但失败了: {failures}"


# ── 4. 漂移检测逻辑单元测试 ──────────────────────────────────────────────────

class TestDriftCheckerLogic:
    """验证基线漂移检测逻辑（不依赖真实评估结果）。"""

    def test_no_baseline_always_passes(self, drift_checker) -> None:
        """基线未初始化时，漂移检查应始终通过（不阻断 CI）。"""
        bad = {"faithfulness": 0.1, "answer_relevancy": 0.1,
               "context_precision": 0.1, "context_recall": 0.1}
        failures = drift_checker(bad)
        assert failures == [], "基线为空时不应触发漂移告警"

    def test_drift_within_tolerance_passes(
        self,
        thresholds: dict[str, Any],
        baseline,
    ) -> None:
        """在容忍范围内的小幅波动不应触发漂移告警。"""
        if baseline is None:
            pytest.skip("基线未初始化，跳过漂移测试")
        baseline_vals = baseline["overall_metrics"]
        # 每项指标退步 0.01（容忍范围是 -0.05），应该通过
        metrics = {k: baseline_vals[k] - 0.01 for k in REQUIRED_METRIC_KEYS}
        from tests.rag_quality.conftest import EVAL_DIR
        import json
        thr = json.loads((EVAL_DIR / "thresholds.json").read_text(encoding="utf-8"))

        def _drift_check(m):
            failures = []
            dg = thr["drift_gates"]
            for key in REQUIRED_METRIC_KEYS:
                delta = m[key] - baseline_vals[key]
                if delta < dg[f"{key}_delta_min"]:
                    failures.append(f"{key}: {delta:+.3f}")
            return failures

        assert _drift_check(metrics) == []


# ── 5. 基线文件格式校验 ──────────────────────────────────────────────────────

class TestBaselineSchema:
    """确保 baseline.json 格式正确（无论是否已初始化）。"""

    def test_baseline_file_exists(self) -> None:
        assert (EVAL_DIR / "baseline.json").exists(), (
            "baseline.json 不存在，请先运行: "
            "python tests/rag_quality/run_rag_quality.py --save-baseline"
        )

    def test_baseline_has_overall_metrics_key(self) -> None:
        import json
        data = json.loads((EVAL_DIR / "baseline.json").read_text(encoding="utf-8"))
        assert "overall_metrics" in data, "baseline.json 缺少 overall_metrics"

    def test_baseline_overall_metrics_has_correct_keys(self) -> None:
        import json
        data = json.loads((EVAL_DIR / "baseline.json").read_text(encoding="utf-8"))
        overall = data["overall_metrics"]
        for key in REQUIRED_METRIC_KEYS:
            assert key in overall, f"baseline.json overall_metrics 缺少 {key}"

    def test_initialized_baseline_values_in_range(self, baseline) -> None:
        """已初始化的基线值应在 [0, 1] 范围内。"""
        if baseline is None:
            pytest.skip("基线未初始化，跳过数值范围校验")
        for key in REQUIRED_METRIC_KEYS:
            val = baseline["overall_metrics"].get(key)
            if val is not None:
                assert 0.0 <= val <= 1.0, f"baseline {key}={val} 超出 [0,1]"
