# -*- coding: utf-8 -*-
import importlib


def test_confirmation_gate_skip_mode_bypasses_interrupt(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.confirmation_gate")

    def _unexpected_interrupt(payload):  # pragma: no cover - should never run
        raise AssertionError("interrupt should not be called when confirmation_mode=skip")

    monkeypatch.setattr(module, "interrupt", _unexpected_interrupt)
    out = module.confirmation_gate(
        {
            "output_mode": "investment_report",
            "confirmation_mode": "skip",
        }
    )
    assert out == {}


def test_confirmation_gate_required_mode_forces_interrupt(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.confirmation_gate")
    captured: dict = {}

    def _fake_interrupt(payload):
        captured.update(payload)
        return "确认执行"

    monkeypatch.setattr(module, "interrupt", _fake_interrupt)
    out = module.confirmation_gate(
        {
            "output_mode": "brief",
            "confirmation_mode": "required",
            "plan_ir": {"rationale": "test plan", "required_agents": ["news_agent"]},
        }
    )
    assert out.get("user_confirmation") == "确认执行"
    assert out.get("require_confirmation") is False
    assert captured.get("required_agents") == ["news_agent"]
    assert captured.get("prompt") == "执行计划确认"
    assert captured.get("options") == ["确认执行", "调整参数", "取消"]


def test_confirmation_gate_explicit_require_false_has_highest_priority(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.confirmation_gate")

    def _unexpected_interrupt(payload):  # pragma: no cover - should never run
        raise AssertionError("interrupt should not be called when require_confirmation=False")

    monkeypatch.setattr(module, "interrupt", _unexpected_interrupt)
    out = module.confirmation_gate(
        {
            "output_mode": "investment_report",
            "confirmation_mode": "required",
            "require_confirmation": False,
        }
    )
    assert out == {}


def test_confirmation_gate_invalid_mode_falls_back_to_auto(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.confirmation_gate")
    captured: dict = {}

    def _fake_interrupt(payload):
        captured.update(payload)
        return "确认执行"

    monkeypatch.setattr(module, "interrupt", _fake_interrupt)
    out = module.confirmation_gate(
        {
            "output_mode": "investment_report",
            "confirmation_mode": "invalid_mode",
        }
    )
    assert out.get("user_confirmation") == "确认执行"
    assert out.get("confirmation_mode") == "auto"
