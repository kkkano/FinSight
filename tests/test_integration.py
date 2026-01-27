# -*- coding: utf-8 -*-
"""
此脚本用于全面测试 Finsight 项目的API端点和核心Agent功能。
它使用 pytest 框架，并为需要 LLM 的测试提供了跳过机制。
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# 将项目根目录添加到 sys.path 中，以确保可以正确导入模块
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 晚一点导入 `app` 和 `FinsightAgent`，在 sys.path 设置好之后
from fastapi_service import app
from agent import FinsightAgent
from rag_integration import run_langchain_agent # 导入 Langchain agent

# 创建一个用于测试的 FastAPI TestClient 实例
client = TestClient(app)

# ===================================================================
# API 端点测试
# ===================================================================

def test_read_root():
    """测试根端点是否返回欢迎信息"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the Finsight API"}

@pytest.mark.llm_required
@patch('fastapi_service.FinsightAgent')
def test_analyze_endpoint_success(mock_agent):
    """测试 /analyze 端点在成功情况下的行为"""
    # 模拟 FinsightAgent 的 run 方法返回一个成功的结果
    mock_agent.return_value.run.return_value = "分析报告: 这是关于AAPL的详细分析。"

    response = client.post("/analyze", json={"query": "分析 AAPL"})

    assert response.status_code == 200
    assert response.json() == {"result": "分析报告: 这是关于AAPL的详细分析。"}
    # 验证 FinsightAgent 是否被正确调用
    mock_agent.return_value.run.assert_called_once_with(query="分析 AAPL")

@pytest.mark.llm_required
@patch('fastapi_service.FinsightAgent')
def test_analyze_endpoint_agent_error(mock_agent):
    """测试当 Agent 内部出错时 /analyze 端点的行为"""
    # 模拟 FinsightAgent 的 run 方法抛出异常
    mock_agent.return_value.run.side_effect = Exception("LLM 服务暂时不可用")

    response = client.post("/analyze", json={"query": "分析 AAPL"})

    assert response.status_code == 500
    assert "LLM 服务暂时不可用" in response.json()["detail"]

# ===================================================================
# 核心 Agent 功能测试 (使用模拟的 LLM 调用)
# ===================================================================

@pytest.fixture
def mock_llm_call():
    """提供一个模拟的 call_llm 函数，用于 Agent 测试"""
    # 这个 mock 将根据收到的消息历史返回不同的预设响应
    def mock_call(provider, model, messages):
        last_message = messages[-1]['content']
        if "get_current_datetime" in last_message:
            return """Thought: 我需要先获取当前时间。
Action:
```json
{"tool_name": "get_current_datetime", "tool_input": {}}
```"""
        elif "Observation: 2025" in last_message: # 假设获取时间后的观察结果
            return """Thought: 时间已获取，现在我需要搜索关于 'NVDA' 的信息。
Action:
```json
{"tool_name": "search", "tool_input": {"query": "NVIDIA stock news"}}
```"""
        elif "Observation: Search Results:" in last_message:
             return """Thought: 我已经有了一些新闻，现在我想分析一下新闻的情绪。
Action:
```json
{"tool_name": "analyze_news_sentiment", "tool_input": {"topic": "NVIDIA stock"}}
```"""
        elif "Observation: 新闻情感分析报告" in last_message:
            return """Thought: 我已经收集了足够的信息，可以生成最终报告了。
Final Answer:
# 英伟达(NVDA) - 专业分析报告
*报告日期: 2025-10-19*

## 摘要
基于近期强劲的新闻情绪和搜索结果，我们对英伟达持积极看法。
"""
        return "Final Answer: 无法处理该请求。"

    # 使用 patch 来替换真实的 call_llm
    with patch('agent.call_llm', side_effect=mock_call) as mocked_llm:
        yield mocked_llm

def test_finsight_agent_run_workflow(mock_llm_call):
    """测试 FinsightAgent 是否能成功完成一个多步骤的工作流"""
    agent_instance = FinsightAgent()
    final_report = agent_instance.run(user_query="分析 NVDA")

    # 验证最终报告是否符合预期
    assert "英伟达(NVDA) - 专业分析报告" in final_report
    assert "报告日期: 2025-10-19" in final_report # 注意年份可能需要根据实际情况调整
    assert "新闻情绪" in final_report

    # 验证 LLM 被调用的次数
    assert mock_llm_call.call_count == 4 # datetime -> search -> sentiment -> final answer

    # 验证 observation_count 是否正确增加
    # 这里的数字取决于 mock_llm_call 的设计，3个工具调用 + 1个 get_current_datetime
    assert agent_instance.observations_count >= 3


# ===================================================================
# RAG / Langchain Agent 测试
# ===================================================================

@pytest.mark.llm_required
@patch('rag_integration.agent_executor.invoke')
def test_run_langchain_agent(mock_invoke):
    """测试 Langchain Agent 的调用逻辑"""
    # 模拟 Langchain agent_executor 的返回
    mock_invoke.return_value = {
        "input": "分析 NVDA",
        "output": "这是由 Langchain Agent 生成的关于 NVDA 的分析报告。"
    }

    result = run_langchain_agent("分析 NVDA")

    assert result is not None
    assert "Langchain Agent" in result["output"]
    # 验证 invoke 方法是否被正确调用
    mock_invoke.assert_called_once_with({"input": "分析 NVDA"})


# ===================================================================
# Pytest 配置文件说明 (pytest.ini)
# ===================================================================
# 为了管理需要 LLM API 密钥的测试，您可以在项目根目录创建一个 `pytest.ini` 文件，内容如下：
#
# [pytest]
# markers =
#     llm_required: marks tests that require a live LLM API key to run
#
# 然后，您可以使用以下命令来运行测试：
#
# - 运行所有测试 (会跳过需要 LLM 的测试，除非已配置密钥且无跳过逻辑):
#   pytest
#
# - 只运行不需要 LLM 的测试:
#   pytest -m "not llm_required"
#
# - 只运行需要 LLM 的测试 (前提是您已配置好 API 密钥):
#   pytest -m "llm_required"
#
# 默认情况下，如果缺少 OPENAI_API_KEY，测试会失败。
# 我们可以添加一个跳过逻辑：
# llm_required = pytest.mark.skipif(
#     not os.environ.get("OPENAI_API_KEY"), reason="需要 OPENAI_API_KEY 环境变量"
# )
# 然后在测试函数上使用 `@llm_required` 而不是 `@pytest.mark.llm_required`
