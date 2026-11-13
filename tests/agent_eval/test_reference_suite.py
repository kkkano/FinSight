"""根pytest中的活动对照门禁；旧测试始终在独立进程完整执行。"""
from pathlib import Path
import subprocess
import sys


def test_retired_reference_contracts_remain_executable():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-B", str(root / "tests/agent_eval/reference/run_tests.py"), "-q", "--tb=short"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert result.returncode == 0, result.stdout[-14000:] + result.stderr[-2000:]
