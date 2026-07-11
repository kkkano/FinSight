# -*- coding: utf-8 -*-
"""WP3 Task 8 收尾门禁。"""
from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.agents_router import AgentsRouterDeps, create_agents_router


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SHIMS = (
    "backend/api/agent_router.py",
    "backend/api/rebalance_schemas.py",
    "backend/graph/nodes/chat_renderer.py",
    "backend/graph/nodes/conversation_router.py",
    "backend/graph/nodes/execute_plan_stub.py",
    "backend/graph/nodes/planner_stub.py",
    "backend/graph/nodes/render_stub.py",
)
SILENT_PASS_ROOTS = (
    "backend/api",
    "backend/graph/intent",
    "backend/graph/planning",
    "backend/graph/render_vars",
    "backend/graph/renderers",
    "backend/report",
    "backend/services/rebalance",
)


class _Profile:
    def __init__(self) -> None:
        self.preferences: dict = {}


class _MemoryService:
    def __init__(self) -> None:
        self.profile = _Profile()

    def get_user_profile(self, _user_id: str) -> _Profile:
        return self.profile

    def update_user_profile(self, profile: _Profile) -> bool:
        self.profile = profile
        return True


def test_agents_router_owns_catalog_and_preferences() -> None:
    app = FastAPI()
    app.include_router(create_agents_router(AgentsRouterDeps(memory_service=_MemoryService())))
    client = TestClient(app)

    assert client.get("/api/agents").status_code == 200
    update = client.put(
        "/api/agents/preferences",
        json={"user_id": "u1", "preferences": {"timeoutSeconds": 75}},
    )
    assert update.status_code == 200
    assert update.json()["preferences"]["timeoutSeconds"] == 75
    loaded = client.get("/api/agents/preferences", params={"user_id": "u1"})
    assert loaded.status_code == 200
    assert loaded.json()["preferences"]["timeoutSeconds"] == 75


def test_wp3_legacy_shims_are_removed() -> None:
    remaining = [path for path in LEGACY_SHIMS if (REPO_ROOT / path).exists()]
    assert remaining == []


def test_wp3_touched_files_have_no_silent_exception_pass() -> None:
    violations: list[str] = []
    for root in SILENT_PASS_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                for handler in node.handlers:
                    if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                        violations.append(f"{path.relative_to(REPO_ROOT)}:{handler.lineno}")
    assert violations == []


def test_wp3_python_size_gates() -> None:
    main_lines = len((REPO_ROOT / "backend/api/main.py").read_text(encoding="utf-8-sig").splitlines())
    assert main_lines <= 120, f"backend/api/main.py has {main_lines} lines"

    oversized: list[str] = []
    for path in (REPO_ROOT / "backend/graph/nodes").glob("*.py"):
        lines = len(path.read_text(encoding="utf-8-sig").splitlines())
        if lines > 900:
            oversized.append(f"{path.name}:{lines}")
    assert oversized == []
