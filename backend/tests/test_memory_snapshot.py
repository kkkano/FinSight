from backend.graph.memory_snapshot import build_checkpoint_memory


def test_unknown_subject_does_not_overwrite_checkpoint_memory() -> None:
    memory = build_checkpoint_memory(
        state={
            "query": "你好",
            "subject": {"subject_type": "unknown", "tickers": []},
            "memory_context": {"current_thread_focus": {"ticker": "AAPL"}},
        },
        rendered_artifacts={"draft_markdown": "你好，有什么可以帮你？"},
    )
    assert memory is None


def test_checkpoint_memory_captures_focus_and_report_without_file_storage() -> None:
    memory = build_checkpoint_memory(
        state={
            "query": "生成 AAPL 研究报告",
            "output_mode": "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        },
        rendered_artifacts={
            "research_synthesis": {
                "overall_conclusion": "盈利质量稳定，但估值对利率敏感。",
                "risks": ["估值对利率敏感"],
                "task_results": [{"title": "基本面"}, {"title": "风险"}],
            },
            "draft_markdown": "# AAPL 研究报告",
        },
    )

    assert memory is not None
    assert memory["current_thread_focus"]["ticker"] == "AAPL"
    assert memory["current_thread_focus"]["last_report"] == memory["current_report"]
    assert memory["current_report"]["title"] == "AAPL 研究报告"
    assert memory["current_report"]["risks"] == ["估值对利率敏感"]


def test_non_report_followup_preserves_current_report() -> None:
    report = {"title": "AAPL 研究报告", "ticker": "AAPL"}
    memory = build_checkpoint_memory(
        state={
            "query": "那最大的风险呢？",
            "output_mode": "chat",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "memory_context": {"current_report": report},
        },
        rendered_artifacts={"draft_markdown": "最大风险是估值对利率变化敏感。"},
    )

    assert memory is not None
    assert memory["current_report"] == report
    assert memory["current_thread_focus"]["last_report"] == report
