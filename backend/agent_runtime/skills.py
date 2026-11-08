"""原生研究复用现有技能清单；技能只提供指导，不改变执行权限或预算。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.skills.registry import get_builtin_skill_registry
from backend.skills.schema import SkillManifest


MAX_SKILLS_PER_REQUEST = 3


def _catalog_entry(manifest: SkillManifest) -> dict[str, str]:
    return {"id": manifest.name, "name": manifest.display_name or manifest.name,
            "description": manifest.description, "category": manifest.category or "framework"}


def skill_catalog() -> list[dict[str, str]]:
    """只返回已安装 manifest 的展示信息，供用户和当前 Agent 按问题选取。"""
    return [_catalog_entry(manifest) for manifest in get_builtin_skill_registry().all()]


def validate_skill_ids(skill_ids: Any) -> list[str]:
    """校验显式选择或模型选取的技能；未知名称不变成文件路径或临时技能。"""
    if skill_ids is None:
        return []
    if not isinstance(skill_ids, list) or len(skill_ids) > MAX_SKILLS_PER_REQUEST:
        raise ValueError("skill_ids_must_be_list_of_at_most_3")
    registry = get_builtin_skill_registry()
    selected: list[str] = []
    for skill_id in skill_ids:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id_must_be_nonempty_string")
        normalized = skill_id.strip()
        if registry.get(normalized) is None:
            raise ValueError("skill_not_found")
        if normalized not in selected:
            selected.append(normalized)
    return selected


def skill_guidance(skill_id: str) -> dict[str, Any]:
    """给当前主/专业 Agent 的研究指导；不加载工具、不分派 Agent、不采用 manifest 预算。"""
    selected = validate_skill_ids([skill_id])[0]
    manifest = get_builtin_skill_registry().get(selected)
    return {
        **_catalog_entry(manifest),
        "perspective": manifest.perspective,
        "output_contract": deepcopy(manifest.output_contract),
        "preferred_tools": list(manifest.preferred_tools),
        "preferred_agents": list(manifest.preferred_agents),
        "optional_python_operations": list(manifest.optional_python_operations),
        "usage_note": "按当前问题采用相关视角与输出要求。工具、Agent 和计算操作仅为建议，"
                      "仍以当前角色实际可用能力为准；不能增加权限、改变预算或绕过操作确认。",
    }
