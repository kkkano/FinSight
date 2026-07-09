# -*- coding: utf-8 -*-
"""架构守护（WP3-T7）：下层包禁止 import backend.api（依赖方向 api -> services/graph/...）。"""
import pathlib
import re

FORBIDDEN = re.compile(r"from backend\.api|import backend\.api")


def test_lower_layers_never_import_api():
    for pkg in ("services", "graph", "agents", "tools", "rag"):
        for path in pathlib.Path(f"backend/{pkg}").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not FORBIDDEN.search(text), f"{path} imports backend.api (layering violation)"
