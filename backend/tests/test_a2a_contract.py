# -*- coding: utf-8 -*-


def test_a2a_adapter_disabled_by_default(monkeypatch):
    monkeypatch.delenv("A2A_SERVER_ENABLED", raising=False)

    from backend.protocols.a2a_server import build_agent_card, submit_task

    card = build_agent_card()
    assert card["enabled"] is False
    assert card["capabilities"]["streaming"] is True

    result = submit_task({"message": "research NVDA"})
    assert result["status"] == "disabled"
    assert result["error"]["code"] == "a2a_server_disabled"


def test_agent_card_describes_research_skills_when_enabled(monkeypatch):
    monkeypatch.setenv("A2A_SERVER_ENABLED", "true")

    from backend.protocols.a2a_server import build_agent_card

    card = build_agent_card()

    assert card["enabled"] is True
    skill_ids = {skill["id"] for skill in card["skills"]}
    assert {
        "company_deep_research",
        "portfolio_diagnosis",
        "holdings_change_investigation",
    }.issubset(skill_ids)
    assert card["capabilities"]["streaming"] is True
    assert card["defaultInputModes"] == ["application/json", "text/plain"]


def test_submit_task_maps_payload_to_execute_request(monkeypatch):
    monkeypatch.setenv("A2A_SERVER_ENABLED", "true")

    from backend.protocols.a2a_server import build_execute_request, submit_task

    payload = {
        "message": "Investigate NVDA holdings changes",
        "metadata": {
            "session_id": "tenant:user:a2a",
            "tickers": ["NVDA"],
            "skill": "holdings_change_investigation",
        },
    }

    execute_request = build_execute_request(payload)
    assert execute_request["query"] == "Investigate NVDA holdings changes"
    assert execute_request["session_id"] == "tenant:user:a2a"
    assert execute_request["tickers"] == ["NVDA"]
    assert execute_request["analysis_depth"] == "deep_research"
    assert execute_request["source"] == "a2a"
    assert execute_request["output_mode"] == "investment_report"

    submitted = submit_task(payload)
    assert submitted["status"] == "submitted"
    assert submitted["task_id"].startswith("a2a_task_")
    assert submitted["execute_request"]["query"] == "Investigate NVDA holdings changes"


def test_stream_task_emits_state_and_final_artifacts(monkeypatch):
    monkeypatch.setenv("A2A_SERVER_ENABLED", "true")

    from backend.protocols.a2a_server import stream_task, submit_task

    submitted = submit_task({"message": "Research AAPL", "metadata": {"tickers": ["AAPL"]}})
    events = list(stream_task(submitted["task_id"]))

    assert [event["kind"] for event in events] == ["task_state", "task_state", "artifact"]
    assert events[0]["state"] == "submitted"
    assert events[1]["state"] == "working"
    assert events[-1]["artifact"]["execute_request"]["query"] == "Research AAPL"


def test_get_task_artifacts_returns_submitted_execute_request(monkeypatch):
    monkeypatch.setenv("A2A_SERVER_ENABLED", "true")

    from backend.protocols.a2a_server import get_task_artifacts, submit_task

    submitted = submit_task({"message": "Diagnose portfolio", "metadata": {"skill": "portfolio_diagnosis"}})
    artifacts = get_task_artifacts(submitted["task_id"])

    assert artifacts["status"] == "submitted"
    assert artifacts["execute_request"]["source"] == "a2a"
    assert artifacts["execute_request"]["query"] == "Diagnose portfolio"
