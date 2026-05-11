# -*- coding: utf-8 -*-
from backend.graph.nodes.render_stub import render_stub


def test_url_fetch_failure_stays_on_url_failure_without_generic_focus_line() -> None:
    result = render_stub(
        {
            "query": "Read https://example.com/empty and disclose if no usable content is available.",
            "output_mode": "chat",
            "subject": {"subject_type": "research_doc", "tickers": []},
            "operation": {"name": "qa"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "research_doc",
                    "tickers": [],
                    "operation": {"name": "qa", "params": {"url": "https://example.com/empty"}},
                }
            ],
            "plan_ir": {
                "steps": [
                    {
                        "id": "s1",
                        "kind": "tool",
                        "name": "fetch_url_content",
                        "inputs": {"url": "https://example.com/empty"},
                        "task_ids": ["task_1"],
                    }
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": {
                            "url": "https://example.com/empty",
                            "error": "404 Client Error",
                            "content": "",
                        }
                    }
                }
            },
        }
    )

    markdown = result["artifacts"]["draft_markdown"]
    content_lines = [line for line in markdown.splitlines() if line.strip()]
    assert len(content_lines) == 1
    assert "https://example.com/empty" in markdown
