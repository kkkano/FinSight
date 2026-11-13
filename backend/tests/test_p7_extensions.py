# -*- coding: utf-8 -*-
from backend.tools.python_compute import run_python_compute


def test_python_compute_growth_chart_returns_svg_artifact():
    result = run_python_compute(
        dataset_refs=["step:get_sec_company_facts_quarterly"],
        operation="growth_chart",
        params={"metric": "revenue"},
        datasets={
            "step:get_sec_company_facts_quarterly": {
                "quarterly": [
                    {"period": "2025Q1", "revenue": 100.0},
                    {"period": "2025Q2", "revenue": 130.0},
                    {"period": "2025Q3", "revenue": 160.0},
                ]
            }
        },
    )

    assert result["charts"][0]["format"] == "svg"
    assert "<svg" in result["charts"][0]["svg"]
    assert result["charts"][0]["input_refs"] == ["step:get_sec_company_facts_quarterly"]


def test_thread_workspace_writes_and_reads_notes(tmp_path):
    from backend.workspace.thread_workspace import ThreadWorkspace

    workspace = ThreadWorkspace(root=tmp_path)
    note = workspace.append_note(thread_id="thread-1", content="NVDA valuation sanity checked.")

    assert note.path.name == "notes.md"
    assert "NVDA valuation" in workspace.read_notes("thread-1")
    assert note.thread_id == "thread-1"
