"""
RAG 生成质量评估 - pytest fixtures

所有 fixture 均为纯数据 / 纯逻辑，不依赖真实 LLM 或向量数据库，
保证 pytest 在 CI 环境中毫秒级完成。
真实 RAGAS 评估请使用 run_rag_quality.py CLI。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ── 路径常量 ────────────────────────────────────────────────────────────────

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "dataset.json"
THRESHOLDS_PATH = EVAL_DIR / "thresholds.json"
BASELINE_PATH = EVAL_DIR / "baseline.json"
REPORTS_DIR = EVAL_DIR / "reports"

REQUIRED_CASE_FIELDS = {"id", "doc_type", "question", "ground_truth", "mock_contexts"}
VALID_DOC_TYPES = {"filing", "transcript", "news"}
REQUIRED_METRIC_KEYS = {
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
}


# ── 数据 fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def dataset() -> dict[str, Any]:
    """加载黄金数据集。"""
    assert DATASET_PATH.exists(), f"数据集文件不存在: {DATASET_PATH}"
    with DATASET_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def dataset_cases(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """提取所有评估案例列表。"""
    return dataset["cases"]


@pytest.fixture(scope="session")
def thresholds() -> dict[str, Any]:
    """加载阈值配置。"""
    assert THRESHOLDS_PATH.exists(), f"阈值配置文件不存在: {THRESHOLDS_PATH}"
    with THRESHOLDS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def baseline() -> dict[str, Any] | None:
    """加载基线结果（如果存在且已初始化则返回，否则返回 None）。"""
    if not BASELINE_PATH.exists():
        return None
    with BASELINE_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    # 基线未初始化（overall_metrics 全为 null）时返回 None
    if data.get("overall_metrics", {}).get("faithfulness") is None:
        return None
    return data


# ── 工具函数 fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def gate_checker(thresholds: dict[str, Any]):
    """
    返回一个可调用对象，用于检查指标是否通过全局门控。

    用法：
        failed = gate_checker({"faithfulness": 0.82, "answer_relevancy": 0.76, ...})
        assert not failed, f"门控失败: {failed}"
    """
    metric_cfg = thresholds["metrics"]

    def _check(metrics: dict[str, float]) -> list[str]:
        """返回所有未通过门控的描述列表，空列表表示全部通过。"""
        failures: list[str] = []
        for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            min_val = metric_cfg[key]["min"]
            actual = metrics.get(key)
            if actual is None:
                failures.append(f"{key}: 缺失")
            elif actual < min_val:
                failures.append(f"{key}: {actual:.3f} < 最低要求 {min_val}")
        return failures

    return _check


@pytest.fixture(scope="session")
def drift_checker(thresholds: dict[str, Any], baseline: dict[str, Any] | None):
    """
    返回一个可调用对象，检测指标相对基线的漂移。
    若基线未初始化，则漂移检查始终通过。
    """
    drift_gates = thresholds["drift_gates"]

    def _check(metrics: dict[str, float]) -> list[str]:
        if baseline is None:
            return []
        baseline_overall = baseline.get("overall_metrics", {})
        failures: list[str] = []
        for key, delta_min in {
            "faithfulness": drift_gates["faithfulness_delta_min"],
            "answer_relevancy": drift_gates["answer_relevancy_delta_min"],
            "context_precision": drift_gates["context_precision_delta_min"],
            "context_recall": drift_gates["context_recall_delta_min"],
        }.items():
            baseline_val = baseline_overall.get(key)
            actual = metrics.get(key)
            if baseline_val is None or actual is None:
                continue
            delta = actual - baseline_val
            if delta < delta_min:
                failures.append(
                    f"{key}: 漂移 {delta:+.3f} < 允许最大退步 {delta_min}"
                )
        return failures

    return _check


# ── Mock 指标 fixtures（用于门控逻辑单元测试）───────────────────────────────

@pytest.fixture
def passing_metrics() -> dict[str, float]:
    """刚好全部通过默认阈值的指标集合。"""
    return {
        "faithfulness": 0.85,
        "answer_relevancy": 0.80,
        "context_precision": 0.75,
        "context_recall": 0.75,
    }


@pytest.fixture
def failing_metrics() -> dict[str, float]:
    """faithfulness 和 context_recall 低于阈值的指标集合。"""
    return {
        "faithfulness": 0.72,   # < 0.80，应该失败
        "answer_relevancy": 0.80,
        "context_precision": 0.75,
        "context_recall": 0.65,  # < 0.70，应该失败
    }
