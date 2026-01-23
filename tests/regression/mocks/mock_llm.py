# -*- coding: utf-8 -*-
"""
Mock LLM for Regression Testing
规则匹配，不调用真实 LLM
"""
from typing import Any, List
from dataclasses import dataclass


@dataclass
class MockAIMessage:
    content: str


class MockLLM:
    """Mock LLM - 基于规则返回响应"""

    async def ainvoke(self, messages: List[Any]) -> MockAIMessage:
        if not messages:
            return MockAIMessage(content="No input provided")

        last_msg = messages[-1]
        content = getattr(last_msg, "content", str(last_msg))

        # Forum synthesis mock
        if "首席金融分析师" in content or "EXECUTIVE SUMMARY" in content:
            return MockAIMessage(content=self._mock_forum_response())

        # News analysis mock
        if "新闻分析" in content or "市场影响" in content:
            return MockAIMessage(content="[Mock] 新闻分析显示市场情绪偏向乐观，短期影响有限。")

        # Price context mock
        if "价格数据" in content:
            return MockAIMessage(content="[Mock] 当前价格处于合理区间。")

        # Default
        return MockAIMessage(content="[Mock LLM Response] Analysis completed.")

    def invoke(self, messages: List[Any]) -> MockAIMessage:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.ainvoke(messages))

    async def astream(self, messages: List[Any]):
        response = await self.ainvoke(messages)
        for char in response.content:
            yield MockAIMessage(content=char)

    def _mock_forum_response(self) -> str:
        return """### 1. 📊 执行摘要 (EXECUTIVE SUMMARY)
- **投资评级**: HOLD (观望)
- **目标价位**: 基于当前数据评估中
- **风险等级**: 中等
- **核心观点**: 基于 Mock 数据分析，建议保持观望态度。

### 2. 📈 当前市场表现 (MARKET POSITION)
- 价格处于合理区间
- 成交量正常
- 技术指标中性

### 3. 💰 基本面分析 (FUNDAMENTAL ANALYSIS)
- 财务状况稳健
- 估值合理

### 4. 🌍 宏观环境与催化剂 (MACRO & CATALYSTS)
- 宏观环境稳定
- 近期无重大催化剂

### 5. ⚠️ 风险评估 (RISK ASSESSMENT)
- 市场波动风险
- 数据延迟风险

### 6. 🎯 投资策略 (INVESTMENT STRATEGY)
- 建议保持观望
- 设置止损保护

### 7. 📐 情景分析 (SCENARIO ANALYSIS)
- **乐观情景**: 上涨 10%
- **悲观情景**: 下跌 5%
- **基准情景**: 震荡

### 8. 📅 关注事件 (MONITORING EVENTS)
- 关注财报发布
- 关注宏观数据"""
