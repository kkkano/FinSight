# -*- coding: utf-8 -*-
"""WP3 模块拆分后的导入与生命周期回归。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_in_fresh_interpreter(source: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_base_agent_import_does_not_eagerly_load_graph_runtime() -> None:
    result = _run_in_fresh_interpreter(
        "from backend.agents.base_agent import AgentOutput, BaseFinancialAgent"
    )

    assert result.returncode == 0, result.stderr


def test_security_limiters_load_dotenv_before_reading_environment() -> None:
    result = _run_in_fresh_interpreter(
        """
import os
import sys
import types

for key in (
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_PER_MINUTE",
    "RATE_LIMIT_WINDOW_SECONDS",
    "CONCURRENCY_LIMIT_ENABLED",
    "GENERATION_MAX_CONCURRENT",
    "GENERATION_MAX_CONCURRENT_PER_CLIENT",
):
    os.environ.pop(key, None)

dotenv = types.ModuleType("dotenv")

def load_dotenv(*args, **kwargs):
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "7"
    os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "13"
    os.environ["CONCURRENCY_LIMIT_ENABLED"] = "false"
    os.environ["GENERATION_MAX_CONCURRENT"] = "17"
    os.environ["GENERATION_MAX_CONCURRENT_PER_CLIENT"] = "3"
    return True

dotenv.load_dotenv = load_dotenv
dotenv.dotenv_values = lambda *args, **kwargs: {}
sys.modules["dotenv"] = dotenv

from backend.api import security_gate

assert security_gate._rate_limiter.enabled is False
assert security_gate._rate_limiter.limit == 7
assert security_gate._rate_limiter.window_seconds == 13
assert security_gate._concurrency_limiter.enabled is False
assert security_gate._concurrency_limiter.max_global == 17
assert security_gate._concurrency_limiter.max_per_client == 3
"""
    )

    assert result.returncode == 0, result.stderr
