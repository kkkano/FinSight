"""生产制品不能包含已退役研究源码；冻结预测例外由manifest锁定。"""
import json
from pathlib import Path

def test_retired_research_sources_are_absent_from_production():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "tests/agent_eval/reference/manifest.json").read_text(encoding="utf-8"))
    retired = [row["origin"] for row in manifest["files"].values() if row["role"] == "retired_production"]
    assert retired
    assert [name for name in retired if (root / name).is_file()] == []
