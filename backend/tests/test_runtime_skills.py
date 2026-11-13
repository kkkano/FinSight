"""公开目录、模型方法与用户显式选择共享 Markdown，不隐式执行研究。"""
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.agent_runtime import skills
from backend.agent_runtime.registry import ToolRegistry
from backend.api.skill_router import create_skill_router


SKILL_TITLES = {
    "valuation-analysis": "估值分析",
    "earnings-interpretation": "财报解读",
    "price-move-attribution": "涨跌归因",
    "news-briefing": "新闻简报",
    "interval-statistics": "区间与技术统计",
    "macro-transmission": "宏观传导",
    "industry-chain-reasoning": "产业链推理",
    "research-report-writing": "研报写作",
    "bull-bear-comparison": "多空对照",
}
SKILLS_DIR = Path(__file__).parents[1] / "agent_runtime" / "skills"


def make_registry(ui_context=None, query=""):
    return ToolRegistry(SimpleNamespace(base_tools={}, ui_context=ui_context or {}, query=query))


def test_catalog_uses_all_runtime_markdown_with_exact_chinese_titles():
    catalog = skills.skill_catalog()
    markdown_ids = {path.stem for path in SKILLS_DIR.glob("*.md")}

    assert len(catalog) == 9
    assert {entry["id"] for entry in catalog} == markdown_ids
    assert {entry["id"]: entry["name"] for entry in catalog} == SKILL_TITLES
    for entry in catalog:
        frontmatter = (SKILLS_DIR / f"{entry['id']}.md").read_text(encoding="utf-8").split("---", 2)[1]
        assert f"title: {entry['name']}\n" in frontmatter
        assert f"when: {entry['description']}\n" in frontmatter
        assert entry["category"] == "framework"
        assert any("\u4e00" <= char <= "\u9fff" for char in entry["description"])


def test_public_catalog_api_returns_only_display_fields():
    app = FastAPI()
    app.include_router(create_skill_router())

    with TestClient(app) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert response.json() == {"skills": skills.skill_catalog()}
    assert all(set(item) == {"id", "name", "description", "category"} for item in response.json()["skills"])


def test_skill_id_validation_normalizes_and_deduplicates_without_reordering():
    assert skills.validate_skill_ids(None) == []
    assert skills.validate_skill_ids([]) == []
    assert skills.validate_skill_ids([" valuation-analysis ", "interval-statistics", "valuation-analysis"]) == [
        "valuation-analysis", "interval-statistics",
    ]


@pytest.mark.parametrize("value,code", [
    ("valuation-analysis", "skill_ids_must_be_list_of_at_most_3"),
    (("valuation-analysis",), "skill_ids_must_be_list_of_at_most_3"),
    (["valuation-analysis"] * 4, "skill_ids_must_be_list_of_at_most_3"),
    ([None], "skill_id_must_be_nonempty_string"),
    ([True], "skill_id_must_be_nonempty_string"),
    ([" "], "skill_id_must_be_nonempty_string"),
    (["not-installed"], "skill_not_found"),
    (["../../secrets"], "skill_not_found"),
    (["估值分析"], "skill_not_found"),
    (["ma-trend"], "skill_not_found"),
    (["growth-quality"], "skill_not_found"),
    (["earnings-impact-investigator"], "skill_not_found"),
])
def test_invalid_skill_selection_is_rejected(value, code):
    with pytest.raises(ValueError, match=f"^{code}$"):
        skills.validate_skill_ids(value)


@pytest.mark.parametrize("skill_id", SKILL_TITLES)
def test_guidance_and_model_tool_return_the_same_complete_markdown_body(skill_id):
    guidance = skills.skill_guidance(skill_id)
    body = (SKILLS_DIR / f"{skill_id}.md").read_text(encoding="utf-8").split("---\n", 2)[2]
    tool = make_registry().available("root", "research_lead")["load_skill"]
    result = tool.invoke({"name": skill_id})

    assert result.status == "ok" and result.kind == "control"
    assert guidance["content"] == result.data == body
    assert guidance["name"] == SKILL_TITLES[skill_id]
    assert not {"budget", "preferred_agents", "preferred_tools", "optional_python_operations"} & guidance.keys()
    assert "不能增加权限" in guidance["usage_note"]


def test_model_index_and_loadable_ids_share_the_public_catalog():
    catalog = skills.skill_catalog()
    registry = make_registry()
    tool = registry.available("root", "research_lead")["load_skill"]

    assert tool.parameters["properties"]["name"]["enum"] == [entry["id"] for entry in catalog]
    assert registry.skills_index().splitlines() == [
        f"- {entry['id']}（{entry['name']}）: {entry['description']}" for entry in catalog
    ]


def test_explicit_selection_supplies_complete_methods_in_order_without_tool_calls():
    registry = make_registry({"skill_ids": [" interval-statistics ", "valuation-analysis", "interval-statistics"]})
    selected = registry.selected_skill_context()

    assert selected == [skills.skill_guidance(name) for name in ["interval-statistics", "valuation-analysis"]]
    assert registry.attempts == []
    assert registry._inflight == {}
    selected[0]["content"] = "修改"
    selected.append({"id": "untrusted"})
    assert registry.selected_skill_context() == [
        skills.skill_guidance(name) for name in ["interval-statistics", "valuation-analysis"]
    ]


@pytest.mark.parametrize("ui_context", [{}, {"skill_ids": []}, {"selected_skills": ["valuation-analysis"]}])
def test_natural_language_and_other_context_do_not_implicitly_select_skills(ui_context):
    registry = make_registry(ui_context, query="请分析估值、新闻和财报，再比较多空观点")

    assert registry.selected_skill_context() == []
    assert registry.attempts == []


def test_explicit_selection_rejects_unknown_ids_before_returning_partial_guidance():
    registry = make_registry({"skill_ids": ["valuation-analysis", "growth-quality"]})
    with pytest.raises(ValueError, match="^skill_not_found$"):
        registry.selected_skill_context()
    assert registry.attempts == []


def test_guidance_and_catalog_return_detached_values_without_private_metadata(tmp_path, monkeypatch):
    body = "\n## 方法\n先核对来源。  \n\n---\n保留正文分隔线与尾部空行。\n\n"
    (tmp_path / "fixture.md").write_text(
        "---\nname: fixture\ntitle: 测试方法\nwhen: 测试视角\n"
        "budget: 999\npreferred_agents: risk_agent\nprivate_token: never-public\n---\n" + body,
        encoding="utf-8",
    )
    monkeypatch.setattr(skills, "_SKILLS_DIR", tmp_path)

    guidance = skills.skill_guidance("fixture")
    assert guidance["content"] == body
    assert set(guidance) == {"id", "name", "description", "category", "content", "usage_note"}
    assert "never-public" not in str(guidance)
    guidance["content"] = "修改"
    catalog = skills.skill_catalog()
    catalog[0]["description"] = "修改"

    assert skills.skill_guidance("fixture")["content"] == body
    assert skills.skill_catalog()[0]["description"] == "测试视角"
    assert "never-public" not in make_registry().skills_index()
    assert make_registry().available("root", "research_lead")["load_skill"].invoke({"name": "fixture"}).data == body


def test_guidance_rejects_unknown_skill_instead_of_loading_arbitrary_instructions():
    with pytest.raises(ValueError, match="^skill_not_found$"):
        skills.skill_guidance("../../unknown-skill")
