"""中性叶子迁移的兼容合同；不把旧语义路由迁入原生控制层。"""
import ast
from dataclasses import asdict
from pathlib import Path

from backend.common import financial_inputs as neutral
from backend.agent_runtime import profiles as native_roles
from backend.agents import profiles as legacy_roles
from backend.graph import research_capabilities as legacy_financial


def test_graph_financial_symbols_forward_to_the_single_neutral_definition():
    assert legacy_financial.FINANCIAL_DEFINITIONS is neutral.FINANCIAL_DEFINITIONS
    assert legacy_financial.FINANCIAL_INPUTS is neutral.FINANCIAL_INPUTS
    assert legacy_financial.financial_metric_inputs is neutral.financial_metric_inputs


def test_financial_input_expansion_keeps_order_deduplication_and_unknown_metrics():
    requested = ["free_cash_flow", "capital_allocation_surplus", "dividend_coverage", "eps", "free_cash_flow"]
    assert neutral.financial_metric_inputs(requested) == (
        "operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid", "eps")
    assert neutral.financial_metric_inputs([]) == ()
    assert neutral.financial_metric_inputs(["revenue"]) == ("revenue",)


def test_provider_fact_schema_keeps_the_neutral_metric_enum():
    from backend.tools import disclosure_financial_facts
    assert disclosure_financial_facts._METRICS is neutral.FINANCIAL_DEFINITIONS
    schema = disclosure_financial_facts.FinancialFactCandidate.model_json_schema()
    assert schema["properties"]["metric"]["enum"] == list(neutral.FINANCIAL_DEFINITIONS)


def test_provider_cash_flow_derivations_keep_values_units_and_input_binding():
    from backend.tools.financial_facts import derive_cash_flow_facts
    context = {"subject": "FIXTURE", "period_start": "2026-01-01", "period_end": "2026-03-31",
               "frequency": "quarterly", "unit": "USD", "reporting_basis": "GAAP",
               "source_url": "https://example.invalid/protocol-fixture"}
    facts = [{**context, "metric": metric, "value": value} for metric, value in (
        ("operating_cash_flow", 100), ("capital_expenditure", 30), ("dividends_paid", 20), ("repurchases_paid", 10))]
    rows = derive_cash_flow_facts(facts, ["free_cash_flow", "capital_allocation_surplus", "dividend_coverage"])
    assert [(row["metric"], row["value"], row["unit"]) for row in rows] == [
        ("free_cash_flow", 70, "USD"), ("capital_allocation_surplus", 40, "USD"), ("dividend_coverage", 3.5, "ratio")]
    assert all(row["source_url"] == context["source_url"] and row["subject"] == "FIXTURE" for row in rows)
    assert [row["metric"] for row in rows[0]["derivation_inputs"]] == list(neutral.FINANCIAL_INPUTS["free_cash_flow"])


def test_role_metadata_and_tool_sets_match_the_unchanged_legacy_catalog():
    native = {key: asdict(value) for key, value in native_roles.AGENT_PROFILES.items()}
    legacy = {key: asdict(value) for key, value in legacy_roles.AGENT_PROFILES.items()}
    assert native == legacy and len(native) == 7
    for key in native:
        assert native_roles.profile(key).tools == legacy_roles.profile(key).tools


def test_native_role_module_has_no_legacy_operation_router_or_old_package_import():
    assert not hasattr(native_roles, "lead_agent_for_operation")
    tree = ast.parse(Path(native_roles.__file__).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith(("backend.graph", "backend.agents")) for module in imports)


def test_native_loop_imports_the_declared_role_host_without_changing_routing_logic():
    from backend.agent_runtime import loop
    tree = ast.parse(Path(loop.__file__).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and any(alias.name == "AGENT_PROFILES" for alias in node.names)]
    assert imports and set(imports) == {"backend.agent_runtime.profiles"}
