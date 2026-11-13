"""从运行时 Markdown 读取技能目录与全文；技能不改变权限、预算或分工。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


MAX_SKILLS_PER_REQUEST = 3
_SKILLS_DIR = Path(__file__).resolve().with_name("skills")
_CATALOG_FIELDS = ("id", "name", "description", "category")


def _load_skills() -> dict[str, dict[str, str]]:
    """只解释仓库技能的平面 frontmatter；正文保持原有 Markdown。"""
    result = {}
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), 0)
        if not lines or lines[0].strip() != "---" or not end:
            raise ValueError("invalid_skill_frontmatter")
        fields = {key.strip(): value.strip() for line in lines[1:end] if ":" in line
                  for key, value in [line.split(":", 1)]}
        if fields.get("name") != path.stem or not fields.get("title") or not fields.get("when"):
            raise ValueError("invalid_skill_frontmatter")
        result[path.stem] = {
            "id": path.stem, "name": fields["title"], "description": fields["when"],
            "category": fields.get("category") or "framework", "content": "".join(lines[end + 1:]),
        }
    return result


def _catalog_entry(skill: dict[str, str]) -> dict[str, str]:
    return {key: skill[key] for key in _CATALOG_FIELDS}


def skill_catalog() -> list[dict[str, str]]:
    """只返回已安装 Markdown 的展示信息，用户和模型共享同一目录。"""
    return [_catalog_entry(skill) for skill in _load_skills().values()]


def _validate_skill_ids(skill_ids: Any, installed: dict[str, dict[str, str]]) -> list[str]:
    if skill_ids is None:
        return []
    if not isinstance(skill_ids, list) or len(skill_ids) > MAX_SKILLS_PER_REQUEST:
        raise ValueError("skill_ids_must_be_list_of_at_most_3")
    selected: list[str] = []
    for skill_id in skill_ids:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id_must_be_nonempty_string")
        normalized = skill_id.strip()
        if normalized not in installed:
            raise ValueError("skill_not_found")
        if normalized not in selected:
            selected.append(normalized)
    return selected


def validate_skill_ids(skill_ids: Any) -> list[str]:
    """校验显式选择；未知或旧名称不猜测映射，也不转换为文件路径。"""
    return _validate_skill_ids(skill_ids, _load_skills())


def skill_guidance(skill_id: str) -> dict[str, Any]:
    """返回方法全文与公开元数据；不加载工具、不分派 Agent、不采用执行预算。"""
    installed = _load_skills()
    selected = _validate_skill_ids([skill_id], installed)[0]
    skill = installed[selected]
    return deepcopy({
        **_catalog_entry(skill), "content": skill["content"],
        "usage_note": "按当前问题采用相关方法。工具、Agent 和计算操作仍以当前角色实际可用能力为准；"
                      "不能增加权限、改变预算或绕过操作确认。",
    })
