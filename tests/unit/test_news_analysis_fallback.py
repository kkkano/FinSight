# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def test_news_analysis_failure_does_not_invent_impact_conclusion():
    """旧 SupervisorAgent 已迁移；守护当前 renderer 的诚实降级合同。"""
    from backend.graph.nodes.render_node import render_node

    result = render_node(
        {
            "query": "分析 TSLA 新闻的影响",
            "output_mode": "chat",
            "subject": {"subject_type": "company", "tickers": ["TSLA"]},
            "operation": {"name": "analyze_impact"},
            "tasks": [
                {
                    "id": "task_news",
                    "subject_type": "company",
                    "tickers": ["TSLA"],
                    "operation": {"name": "analyze_impact", "params": {"topic": "news"}},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "news_1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "TSLA"}}
                ]
            },
            "artifacts": {
                # 模拟新闻工具成功、分析/综合层未产出 impact_analysis 的降级场景。
                "render_vars": {},
                "step_results": {
                    "news_1": {
                        "output": [
                            {
                                "title": "Tesla Q4 earnings beat; gross margin up",
                                "url": "https://example.com/tesla-q4",
                                "source": "unit-test",
                                "published_at": "2026-02-01",
                            }
                        ]
                    }
                },
            },
        }
    )

    response = result["artifacts"]["draft_markdown"]
    assert "Tesla Q4 earnings beat" in response
    assert "没有足够证据支撑进一步影响判断" in response
    assert "利好股价" not in response
    assert "建议买入" not in response
