# -*- coding: utf-8 -*-
"""视角型 skill 扩展测试：

- SkillManifest 解析 perspective/display_name/category（缺失时向后兼容）
- registry 从 yaml 正确加载视角字段
- policy_gate 选中带 perspective 的 skill 后，skill_selection 透传 perspective
- synthesize 把 perspective 注入合成 prompt
"""
from backend.skills.registry import SkillRegistry
from backend.skills.schema import SkillManifest


# --- schema 层：新字段解析 + 向后兼容 ---

def test_manifest_parses_perspective_fields():
    manifest = SkillManifest.from_mapping(
        {
            "name": "chan-theory",
            "description": "Chan theory perspective.",
            "display_name": "缠论",
            "category": "framework",
            "perspective": "识别笔/线段/中枢级别，给出操作级别与买卖点。",
            "required_facets": {"primary_task": "technical_analysis"},
            "preferred_agents": ["technical_agent"],
        }
    )
    assert manifest is not None
    assert manifest.display_name == "缠论"
    assert manifest.category == "framework"
    assert manifest.perspective.startswith("识别笔")


def test_manifest_perspective_fields_default_empty():
    """旧 yaml 无新字段 → 默认空，确保向后兼容。"""
    manifest = SkillManifest.from_mapping({"name": "x", "description": "y"})
    assert manifest is not None
    assert manifest.perspective == ""
    assert manifest.display_name == ""
    assert manifest.category == ""


def test_registry_loads_perspective_from_yaml(tmp_path):
    (tmp_path / "chan.yaml").write_text(
        """
name: chan-theory
display_name: 缠论
category: framework
perspective: |
  以缠论视角：识别笔、线段、中枢级别，给出操作级别与买卖点。
required_facets:
  primary_task: technical_analysis
preferred_agents:
  - technical_agent
""".strip(),
        encoding="utf-8",
    )
    registry = SkillRegistry.from_directory(tmp_path)
    manifest = registry.get("chan-theory")
    assert manifest is not None
    assert manifest.display_name == "缠论"
    assert "中枢" in manifest.perspective


# --- synthesize 层：perspective 注入合成 prompt ---

def test_synthesize_injects_skill_perspective():
    from backend.graph.nodes.synthesize import _skill_perspective_block

    state = {
        "policy": {
            "skill_selection": {
                "selected_skill": "chan-theory",
                "display_name": "缠论",
                "perspective": "识别笔、线段、中枢级别，给出操作级别与买卖点。",
            }
        }
    }
    block = _skill_perspective_block(state)
    assert "<analysis_perspective>" in block
    assert "缠论" in block
    assert "中枢" in block


def test_synthesize_perspective_empty_without_skill():
    """无 skill / 无 perspective → 空串，合成 prompt 与原本一致（向后兼容）。"""
    from backend.graph.nodes.synthesize import _skill_perspective_block

    assert _skill_perspective_block({}) == ""
    assert _skill_perspective_block({"policy": {}}) == ""
    assert _skill_perspective_block({"policy": {"skill_selection": {}}}) == ""
    # 选中 skill 但无 perspective（如现有研究型 skill）→ 仍为空，不注入
    assert _skill_perspective_block({"policy": {"skill_selection": {"selected_skill": "valuation-sanity-check"}}}) == ""


# --- builtin 视角型 skill：真实 registry 加载 + 显式选择 + 不自动抢占 ---

def test_builtin_registry_includes_perspective_skills():
    from backend.skills.registry import get_builtin_skill_registry
    from backend.skills.selector import select_skill_for_facets

    registry = get_builtin_skill_registry()
    chan = registry.get("chan-theory")
    assert chan is not None
    assert chan.display_name == "缠论"
    assert chan.category == "technical"
    assert chan.perspective.strip() != ""
    assert "technical_agent" in chan.preferred_agents

    # 视角型 skill 主要靠显式选择（/skill 或 UI chip → ui_context.skill）
    sel = select_skill_for_facets(
        {"primary_task": "technical_analysis"},
        registry=registry,
        explicit_skill="chan-theory",
    )
    assert sel.selected_skill == "chan-theory"
    assert sel.reason == "explicit_skill"


def test_perspective_skills_do_not_auto_hijack():
    """视角型 skill 无 required_facets → 无显式选择时不会自动抢占技术/估值场景。"""
    from backend.skills.registry import get_builtin_skill_registry
    from backend.skills.selector import select_skill_for_facets

    registry = get_builtin_skill_registry()
    perspective_skills = {"chan-theory", "wave-theory", "ma-trend", "growth-quality"}

    tech = select_skill_for_facets(
        {"primary_task": "technical_analysis", "target_metric": "price_action"},
        registry=registry,
    )
    assert tech.selected_skill not in perspective_skills

    # 估值场景仍由现有研究型 skill 自动命中，不被 growth-quality 抢占
    val = select_skill_for_facets(
        {"primary_task": "valuation_analysis", "target_metric": "valuation"},
        registry=registry,
    )
    assert val.selected_skill not in perspective_skills
