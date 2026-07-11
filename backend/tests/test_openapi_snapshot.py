from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "frontend" / "src" / "api" / "openapi.snapshot.json"


def test_openapi_snapshot_is_current() -> None:
    from backend.api.main import app

    current = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(current, encoding="utf-8")
        return

    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "OpenAPI drift: 后端 schema 变了。删除快照后运行 "
        "`python -m pytest backend/tests/test_openapi_snapshot.py` 重新生成，"
        "并在前端执行 `pnpm gen:api` 同步类型，两个生成物一起提交。"
    )
