# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str
    required_facets: dict[str, Any] = field(default_factory=dict)
    preferred_tools: list[str] = field(default_factory=list)
    preferred_agents: list[str] = field(default_factory=list)
    optional_python_operations: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    eval_cases: list[str] = field(default_factory=list)
    # 视角层（向后兼容，旧 manifest 默认空）：
    perspective: str = ""      # 解读视角（Markdown），注入合成 prompt
    display_name: str = ""     # 中文名（前端 chip / 研究卡回显）
    category: str = ""         # technical|framework|fundamental|event… 前端分组

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "SkillManifest | None":
        name = str(payload.get("name") or "").strip()
        if not name:
            return None
        description = str(payload.get("description") or "").strip()
        return cls(
            name=name,
            description=description,
            required_facets=dict(payload.get("required_facets") or {}),
            preferred_tools=[str(item) for item in payload.get("preferred_tools") or [] if str(item).strip()],
            preferred_agents=[str(item) for item in payload.get("preferred_agents") or [] if str(item).strip()],
            optional_python_operations=[
                str(item) for item in payload.get("optional_python_operations") or [] if str(item).strip()
            ],
            budget=dict(payload.get("budget") or {}),
            output_contract=dict(payload.get("output_contract") or {}),
            risk_level=str(payload.get("risk_level") or "low").strip().lower() or "low",
            eval_cases=[str(item) for item in payload.get("eval_cases") or [] if str(item).strip()],
            perspective=str(payload.get("perspective") or "").strip(),
            display_name=str(payload.get("display_name") or "").strip(),
            category=str(payload.get("category") or "").strip(),
        )


@dataclass(frozen=True)
class SkillSelection:
    selected_skill: str | None
    candidates: list[dict[str, Any]]
    reason: str

    def selected_manifest(self, manifests: dict[str, SkillManifest]) -> SkillManifest | None:
        if not self.selected_skill:
            return None
        return manifests.get(self.selected_skill)
