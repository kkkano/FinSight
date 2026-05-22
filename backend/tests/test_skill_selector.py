# -*- coding: utf-8 -*-
from backend.skills.registry import SkillRegistry
from backend.skills.schema import SkillManifest
from backend.skills.selector import extract_explicit_skill, select_skill_for_facets


def _registry() -> SkillRegistry:
    return SkillRegistry(
        [
            SkillManifest(
                name="earnings-impact-investigator",
                description="Investigate earnings impact on stock price.",
                required_facets={
                    "primary_task": "impact_analysis",
                    "event_type": "earnings",
                    "target_metric": "stock_price",
                },
                preferred_tools=["get_stock_price", "run_python_compute"],
                preferred_agents=["fundamental_agent", "news_agent", "risk_agent"],
                optional_python_operations=["surprise_impact", "growth_rates"],
                budget={"max_agents": 3, "max_tools": 9},
                output_contract={"requires_metrics": True},
                risk_level="medium",
                eval_cases=["earnings_price_impact"],
            ),
            SkillManifest(
                name="valuation-sanity-check",
                description="Check valuation against growth.",
                required_facets={"primary_task": "valuation_analysis", "target_metric": "valuation"},
                preferred_tools=["get_stock_price", "run_python_compute"],
                preferred_agents=["fundamental_agent", "technical_agent", "risk_agent"],
                optional_python_operations=["valuation_sanity"],
                budget={"max_agents": 3, "max_tools": 8},
                output_contract={"requires_metrics": True},
                risk_level="medium",
                eval_cases=["valuation_sanity"],
            ),
        ]
    )


def test_explicit_skill_syntax_is_extracted_without_query_keywords():
    assert extract_explicit_skill("/skill valuation-sanity-check NVDA 估值贵不贵") == "valuation-sanity-check"
    assert extract_explicit_skill("NVDA 估值贵不贵") is None


def test_selector_auto_selects_skill_from_structured_facets():
    selection = select_skill_for_facets(
        {
            "primary_task": "impact_analysis",
            "event_type": "earnings",
            "target_metric": "stock_price",
        },
        registry=_registry(),
    )

    assert selection.selected_skill == "earnings-impact-investigator"
    assert selection.candidates[0]["score"] >= 0.99


def test_selector_keeps_price_short_path_without_skill():
    selection = select_skill_for_facets(
        {"primary_task": "price_lookup", "target_metric": "stock_price"},
        registry=_registry(),
    )

    assert selection.selected_skill is None


def test_selector_allows_explicit_skill_to_raise_priority():
    selection = select_skill_for_facets(
        {"primary_task": "price_lookup", "target_metric": "stock_price"},
        registry=_registry(),
        explicit_skill="valuation-sanity-check",
    )

    assert selection.selected_skill == "valuation-sanity-check"
    assert selection.reason == "explicit_skill"
