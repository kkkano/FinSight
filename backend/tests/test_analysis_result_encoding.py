"""固定测试代码经过真实 worker 返回边界；不证明容器的进程隔离。"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def execute_result(monkeypatch, tmp_path):
    source = Path(__file__).resolve().parents[1] / "analysis_worker/runner.py"
    # runner 的镜像入口使用顶层模块名；测试中绑定同一份生产模块并在结束时恢复。
    monkeypatch.syspath_prepend(str(source.parent))
    for name in ("protocol", "data_access", "finsight"):
        monkeypatch.setitem(sys.modules, name, importlib.import_module("backend.analysis_worker." + name))
    spec = importlib.util.spec_from_file_location("analysis_result_runner", source)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    request = tmp_path / "request.json"
    monkeypatch.setattr(runner, "INPUT", request)

    def execute(code):
        request.write_text(json.dumps({"code": code, "datasets": {}}), encoding="utf-8")
        return runner.run()

    return execute


def test_dataframe_result_preserves_valuation_grid_values(execute_result):
    output = execute_result("""result = pd.DataFrame({
    'PE': [15, 20, 25, 30, 35],
    'EPS_6': [90, 120, 150, 180, 210],
    'EPS_8': [120, 160, 200, 240, 280],
    'EPS_10': [150, 200, 250, 300, 350],
    'EPS_12': [180, 240, 300, 360, 420],
})""")
    assert output["status"] == "ok", output
    assert output["result"] == [
        {"PE": pe, "EPS_6": 6 * pe, "EPS_8": 8 * pe, "EPS_10": 10 * pe, "EPS_12": 12 * pe}
        for pe in (15, 20, 25, 30, 35)
    ]
    assert all(type(value) is int for row in output["result"] for value in row.values())


def test_nested_dataframe_result_preserves_dates_and_numbers(execute_result):
    output = execute_result("""result = {
    'currency': 'USD',
    'tables': [pd.DataFrame({'period_end': [pd.Timestamp('2026-07-26')], 'revenue': [np.int64(96221000000)]})],
}""")
    assert output["status"] == "ok", output
    assert output["result"] == {"currency": "USD", "tables": [[
        {"period_end": "2026-07-26T00:00:00", "revenue": 96221000000}
    ]]}


def test_existing_numpy_and_timestamp_result_encoding_is_preserved(execute_result):
    output = execute_result("""result = {
    'difference': np.int64(14606000000), 'ratio': np.float64(0.125),
    'date': pd.Timestamp('2026-07-26'), 'note': '真实计算口径',
}""")
    assert output["status"] == "ok", output
    assert output["result"] == {"difference": 14606000000, "ratio": 0.125,
                                "date": "2026-07-26T00:00:00", "note": "真实计算口径"}
    assert type(output["result"]["difference"]) is int


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_dataframe_nonfinite_values_remain_rejected(execute_result, value):
    output = execute_result(f"result = pd.DataFrame({{'value': [float('{value}')]}})")
    assert output["status"] == "error"
    assert output["error"] == "analysis_code_or_result_invalid"
    assert output["code_error"]["type"] == "ValueError"
    assert "result" not in output


def test_dataframe_output_still_obeys_one_mib_limit(execute_result):
    output = execute_result("result = pd.DataFrame({'value': ['x' * (1024 * 1024)]})")
    assert output["status"] == "error"
    assert output["error"] == "analysis_output_limit"
    assert "result" not in output


def test_series_is_not_implicitly_converted(execute_result):
    output = execute_result("result = pd.Series([1, 2])")
    assert output["status"] == "error"
    assert output["error"] == "analysis_code_or_result_invalid"
    assert output["code_error"]["type"] == "TypeError"
