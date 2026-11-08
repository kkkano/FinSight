"""技能目录与原生指导复用真实 manifest，不改变权限、预算或 legacy 选择器。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.agent_runtime import skills
from backend.api.skill_router import create_skill_router
from backend.skills.registry import SkillRegistry, get_builtin_skill_registry
from backend.skills.schema import SkillManifest


def test_catalog_uses_all_installed_manifests_with_chinese_display_metadata():
    catalog = skills.skill_catalog()
    registry = get_builtin_skill_registry()
    manifest_ids = {path.stem for path in (Path(__file__).parents[1] / "skills" / "builtin").glob("*.yaml")}

    assert len(catalog) == 7
    assert {entry["id"] for entry in catalog} == manifest_ids
    for entry in catalog:
        manifest = registry.get(entry["id"])
        assert entry == {"id": manifest.name, "name": manifest.display_name,
                         "description": manifest.description, "category": manifest.category}
        assert any("\u4e00" <= char <= "\u9fff" for char in entry["name"])
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
    assert skills.validate_skill_ids([" ma-trend ", "growth-quality", "ma-trend"]) == ["ma-trend", "growth-quality"]


@pytest.mark.parametrize("value,code", [
    ("ma-trend", "skill_ids_must_be_list_of_at_most_3"),
    (("ma-trend",), "skill_ids_must_be_list_of_at_most_3"),
    (["ma-trend"] * 4, "skill_ids_must_be_list_of_at_most_3"),
    ([None], "skill_id_must_be_nonempty_string"),
    ([True], "skill_id_must_be_nonempty_string"),
    ([" "], "skill_id_must_be_nonempty_string"),
    (["not-installed"], "skill_not_found"),
    (["../../secrets"], "skill_not_found"),
])
def test_invalid_skill_selection_is_rejected(value, code):
    with pytest.raises(ValueError, match=f"^{code}$"):
        skills.validate_skill_ids(value)


@pytest.mark.parametrize("skill_id", ["growth-quality", "earnings-impact-investigator"])
def test_guidance_preserves_manifest_perspective_contract_and_recommendations(skill_id):
    manifest = get_builtin_skill_registry().get(skill_id)

    guidance = skills.skill_guidance(skill_id)

    assert guidance["perspective"] == manifest.perspective
    assert guidance["output_contract"] == manifest.output_contract
    assert guidance["preferred_tools"] == manifest.preferred_tools
    assert guidance["preferred_agents"] == manifest.preferred_agents
    assert guidance["optional_python_operations"] == manifest.optional_python_operations
    assert "budget" not in guidance
    assert "不能增加权限" in guidance["usage_note"]


def test_guidance_returns_detached_values_and_never_exposes_manifest_budget(monkeypatch):
    manifest = SkillManifest(name="fixture", description="测试视角", perspective="先核对来源",
                             preferred_tools=["get_stock_price"], preferred_agents=["risk_agent"],
                             budget={"max_tools": 999}, output_contract={"sections": ["证据"]})
    registry = SkillRegistry([manifest])
    monkeypatch.setattr(skills, "get_builtin_skill_registry", lambda: registry)

    guidance = skills.skill_guidance("fixture")
    guidance["preferred_tools"].append("delete_everything")
    guidance["output_contract"]["sections"].append("修改")
    catalog = skills.skill_catalog()
    catalog[0]["description"] = "修改"

    assert manifest.preferred_tools == ["get_stock_price"]
    assert manifest.output_contract == {"sections": ["证据"]}
    assert manifest.budget == {"max_tools": 999}
    assert skills.skill_catalog()[0]["description"] == "测试视角"
    assert "budget" not in guidance


def test_guidance_rejects_unknown_skill_instead_of_loading_arbitrary_instructions():
    with pytest.raises(ValueError, match="^skill_not_found$"):
        skills.skill_guidance("../../unknown-skill")
