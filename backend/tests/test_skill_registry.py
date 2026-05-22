# -*- coding: utf-8 -*-
from backend.skills.registry import SkillRegistry
from backend.skills.schema import SkillManifest


def test_skill_registry_loads_yaml_manifests(tmp_path):
    skill_file = tmp_path / "valuation-sanity-check.yaml"
    skill_file.write_text(
        """
name: valuation-sanity-check
description: Check whether valuation is aligned with growth.
required_facets:
  primary_task: valuation_analysis
preferred_tools:
  - get_stock_price
  - run_python_compute
preferred_agents:
  - fundamental_agent
optional_python_operations:
  - valuation_sanity
budget:
  max_agents: 3
  max_tools: 8
output_contract:
  requires_metrics: true
risk_level: medium
eval_cases:
  - valuation_sanity
""".strip(),
        encoding="utf-8",
    )

    registry = SkillRegistry.from_directory(tmp_path)
    manifest = registry.get("valuation-sanity-check")

    assert isinstance(manifest, SkillManifest)
    assert manifest.name == "valuation-sanity-check"
    assert manifest.preferred_tools == ["get_stock_price", "run_python_compute"]
    assert manifest.budget["max_agents"] == 3


def test_skill_registry_rejects_manifest_without_name(tmp_path):
    (tmp_path / "broken.yaml").write_text("description: missing name\n", encoding="utf-8")

    registry = SkillRegistry.from_directory(tmp_path)

    assert registry.all() == []
