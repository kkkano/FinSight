"""冻结运行时必须与既有实测源码一致；离线选择不调用模型。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from . import run as runner


def test_current_digest_binds_nested_adapters_and_prompts_without_changing_baseline(tmp_path):
    current = tmp_path / "agent_runtime"
    current.mkdir()
    (current / "loop.py").write_text("value = 1\n", encoding="utf-8")
    (current / "prompts").mkdir()
    prompt = current / "prompts" / "system.md"
    prompt.write_text("原始提示", encoding="utf-8")
    (current / "adapters").mkdir()
    adapter = current / "adapters" / "sample.py"
    adapter.write_text("value = 1\n", encoding="utf-8")
    frozen = Path(__file__).parent / "baseline_runtime"
    baseline = runner.runtime_digest(frozen)
    first = runner.runtime_digest(current)
    prompt.write_text("更新提示", encoding="utf-8")
    second = runner.runtime_digest(current)
    adapter.write_text("value = 2\n", encoding="utf-8")
    assert len({first, second, runner.runtime_digest(current)}) == 3
    assert runner.runtime_digest(frozen) == baseline


def test_frozen_runtime_matches_recorded_baseline_and_asset_checksums():
    base = Path(__file__).parent
    snapshot = base / "baseline_runtime"
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    recorded = json.loads((base / "results/m1_serial_baseline_record.json").read_text(encoding="utf-8"))
    assert runner.runtime_digest(snapshot) == manifest["runtime_sha256"] == recorded["runtime_sha256"]
    for relative, checksum in manifest["files"].items():
        assert hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() == checksum


def test_baseline_cli_lists_complete_corpus_without_model_requests():
    result = subprocess.run([sys.executable, "-B", str(Path(runner.__file__).resolve()),
                             "--runtime", "baseline", "--list"], cwd=runner.REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 60
    assert "facts-01 facts" in result.stdout


@pytest.mark.parametrize("selection", [[], ["--runtime", "current"]])
def test_current_cli_lists_complete_corpus_without_model_requests(selection):
    result = subprocess.run([sys.executable, "-B", str(Path(runner.__file__).resolve()),
                             *selection, "--list"], cwd=runner.REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 60
    assert "facts-01 facts" in result.stdout


@pytest.mark.parametrize("runtime_name", ["current", "baseline"])
def test_runtime_selection_loads_service_and_tools_from_expected_package(runtime_name):
    script = f"""
import socket
import sys
from pathlib import Path
sys.path.insert(0, {str(runner.ROOT)!r})
from agent_eval import run
def forbidden_connect(*args, **kwargs):
    raise AssertionError('offline runtime selection must not connect')
socket.socket.connect = forbidden_connect
selected = run.activate_runtime({runtime_name!r})
from backend.agent_runtime import service
assert Path(service.__file__).resolve().parent == selected.resolve()
specs = run.financial_tool_specs({runtime_name!r})
assert specs and 'get_stock_price' in specs
if {runtime_name!r} == 'current':
    from backend.agent_runtime import registry
    assert Path(registry.__file__).resolve().parent == selected.resolve()
    assert 'backend.agent_runtime.tools' not in sys.modules
else:
    from agent_eval.baseline_runtime import tools
    assert Path(tools.__file__).resolve().parent == selected.resolve()
    assert 'backend.agent_runtime.registry' not in sys.modules
    assert not any(getattr(spec, 'enveloped', False) for spec in specs.values())
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=runner.REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr


def test_baseline_dependency_archive_handles_real_record_path_offline():
    script = f"""
import socket
import sys
from pathlib import Path
sys.path.insert(0, {str(runner.ROOT)!r})
from agent_eval import run
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))
run.activate_runtime('baseline')
from backend.agent_runtime.data import RunData
from backend.agents.profiles import AGENT_PROFILES
from backend.graph.execution import evidence_pipeline
assert Path(evidence_pipeline.__file__).is_relative_to(Path({str(runner.ROOT)!r}) / 'agent_eval' / 'reference')
data = RunData('fixture-owner', 'fixture-session', 'fixture-run', 'TEST_A quote')
reference = data.record('get_stock_price', {{'ticker': 'TEST_A'}}, {{'price': 42.5, 'currency': 'USD', 'source': 'fixture', 'as_of': '2026-11-01T12:00:00Z'}})
assert reference in data.records
assert data.records[reference]['output']['price'] == 42.5
assert len(AGENT_PROFILES) == 7
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=runner.REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=40)
    assert result.returncode == 0, result.stderr


def test_current_record_raw_provider_wrapper_works_without_loading_old_graph():
    script = f"""
import json
import socket
import sys
from unittest.mock import patch
sys.path.insert(0, {str(runner.ROOT)!r})
from agent_eval import run
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))
selected = run.activate_runtime('current')
import backend.agent_runtime as package
from backend.agent_runtime import registry
from backend.langchain_tools import FINANCIAL_TOOLS
original_path = list(package.__path__)
raw = {{'price': 42.25, 'currency': 'USD', 'source': 'fixture-provider'}}
provider = next(tool for tool in FINANCIAL_TOOLS if tool.name == 'get_stock_price')
with patch.object(type(provider), 'invoke', return_value=json.dumps(raw)) as invoke:
    specs = run.financial_tool_specs('baseline')
    output = specs['get_stock_price'].invoke({{'ticker': 'FIXTURE'}})
    assert output == raw
    invoke.assert_called_once_with({{'ticker': 'FIXTURE'}})
assert list(package.__path__) == original_path
assert not any(name == 'backend.graph' or name.startswith('backend.graph.') for name in sys.modules)
assert all(getattr(spec, 'enveloped', False) for spec in registry.financial_tools().values())
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=runner.REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=40)
    assert result.returncode == 0, result.stderr
