# 阶段1 实施指南：多Agent架构

> 📅 更新日期: 2025-12-27
> 🎯 目标: 实现 4 个常驻 Agent + Supervisor + ForumHost

---

## 一、实施路线图

```
Week 3: BaseAgent + PriceAgent + NewsAgent
Week 4: TechnicalAgent + FundamentalAgent + Supervisor + ForumHost
```

---

## 二、Day 1-2: 创建基础结构

### 2.1 创建目录

```bash
mkdir backend/agents
touch backend/agents/__init__.py
touch backend/agents/base.py
touch backend/agents/price_agent.py
touch backend/agents/news_agent.py
```

### 2.2 实现 base.py

```python
# backend/agents/base.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from abc import ABC, abstractmethod

@dataclass
class Evidence:
    """证据项"""
    text: str
    source: str
    url: Optional[str] = None
    confidence: float = 0.8

@dataclass
class AgentOutput:
    """Agent 标准输出"""
    agent_name: str
    summary: str
    evidence: List[Evidence] = field(default_factory=list)
    confidence: float = 0.5
    data_sources: List[str] = field(default_factory=list)
    as_of: datetime = field(default_factory=datetime.utcnow)
    fallback_used: bool = False
    risks: List[str] = field(default_factory=list)
    reflection_rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "summary": self.summary,
            "evidence": [{"text": e.text, "source": e.source, "url": e.url} for e in self.evidence],
            "confidence": self.confidence,
            "data_sources": self.data_sources,
            "as_of": self.as_of.isoformat(),
            "fallback_used": self.fallback_used,
            "risks": self.risks,
            "reflection_rounds": self.reflection_rounds,
        }

class BaseFinancialAgent(ABC):
    """金融 Agent 基类"""
    AGENT_NAME: str = "base"
    MAX_REFLECTIONS: int = 2
    CACHE_TTL: int = 60

    def __init__(self, llm=None, cache=None, orchestrator=None):
        self.llm = llm
        self.cache = cache
        self.orchestrator = orchestrator

    @abstractmethod
    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        """子类实现具体的数据获取"""
        pass

    async def research(self, query: str, ticker: str) -> AgentOutput:
        """标准研究流程"""
        # 1. 初始搜索
        results = await self._initial_search(query, ticker)
        summary = await self._summarize(results)

        # 2. 反思循环
        rounds = 0
        for i in range(self.MAX_REFLECTIONS):
            gaps = await self._identify_gaps(summary)
            if not gaps:
                break
            new_data = await self._targeted_search(gaps, ticker)
            summary = await self._update_summary(summary, new_data)
            rounds += 1

        return self._build_output(summary, results, rounds)

    async def _identify_gaps(self, summary: str) -> List[str]:
        """识别知识空白"""
        if self.MAX_REFLECTIONS == 0 or not self.llm:
            return []
        # LLM 调用识别空白
        prompt = f"分析以下摘要，列出缺失的关键信息（JSON数组）：\n{summary}"
        # ... LLM 调用
        return []

    async def _summarize(self, results: Dict) -> str:
        """生成摘要"""
        return str(results)[:500]

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Dict:
        """针对性搜索"""
        return {}

    async def _update_summary(self, old: str, new: Dict) -> str:
        """更新摘要"""
        return old + "\n" + str(new)[:200]

    def _build_output(self, summary: str, results: Dict, rounds: int) -> AgentOutput:
        """构建输出"""
        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            data_sources=results.get("sources", []),
            as_of=datetime.utcnow(),
            fallback_used=results.get("fallback_used", False),
            reflection_rounds=rounds,
        )
```

---

## 三、Day 3-4: 实现 PriceAgent

```python
# backend/agents/price_agent.py
from .base import BaseFinancialAgent, AgentOutput, Evidence
from typing import Dict, Any

class PriceAgent(BaseFinancialAgent):
    """行情 Agent - 无反思循环"""
    AGENT_NAME = "PriceAgent"
    MAX_REFLECTIONS = 0  # 行情数据不需要反思
    CACHE_TTL = 30

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        """获取价格数据"""
        if not self.orchestrator:
            return {"error": "orchestrator not available"}

        result = self.orchestrator.fetch("price", ticker)

        return {
            "data": result.data if result.success else None,
            "source": result.source,
            "sources": result.tried_sources,
            "fallback_used": result.fallback_used,
            "cached": result.cached,
            "success": result.success,
        }

    def _build_output(self, summary: str, results: Dict, rounds: int) -> AgentOutput:
        data = results.get("data", {})
        price = data.get("price") if isinstance(data, dict) else None

        evidence = []
        if price:
            evidence.append(Evidence(
                text=f"当前价格: ${price}",
                source=results.get("source", "unknown"),
            ))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=f"价格数据: {summary[:200]}",
            evidence=evidence,
            confidence=0.9 if results.get("success") else 0.3,
            data_sources=results.get("sources", []),
            fallback_used=results.get("fallback_used", False),
            reflection_rounds=0,
        )
```

---

## 四、Day 5-7: 实现 NewsAgent（含反思）

```python
# backend/agents/news_agent.py
from .base import BaseFinancialAgent, AgentOutput, Evidence
from typing import Dict, Any, List

class NewsAgent(BaseFinancialAgent):
    """新闻 Agent - 含反思循环"""
    AGENT_NAME = "NewsAgent"
    MAX_REFLECTIONS = 2
    CACHE_TTL = 600

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        """获取新闻"""
        news_items = []
        sources = []

        # 尝试多个新闻源
        if self.orchestrator:
            result = self.orchestrator.fetch("news", ticker)
            if result.success and result.data:
                news_items.extend(result.data if isinstance(result.data, list) else [result.data])
                sources.extend(result.tried_sources)

        return {
            "news": news_items,
            "sources": sources,
            "count": len(news_items),
            "fallback_used": len(sources) > 1,
        }

    async def _identify_gaps(self, summary: str) -> List[str]:
        """识别新闻空白"""
        if not self.llm:
            return []

        # 检查是否需要更多信息
        gaps = []
        if "风险" not in summary:
            gaps.append("风险因素")
        if len(summary) < 200:
            gaps.append("更多新闻细节")
        return gaps[:2]  # 最多2个空白

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Dict:
        """针对性搜索"""
        # 使用搜索工具补充
        return {"additional": f"补充搜索: {gaps}"}

    def _build_output(self, summary: str, results: Dict, rounds: int) -> AgentOutput:
        news = results.get("news", [])

        evidence = [
            Evidence(text=item.get("title", str(item))[:100], source="news")
            for item in news[:5]
        ]

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=min(0.9, 0.5 + len(news) * 0.1),
            data_sources=results.get("sources", []),
            fallback_used=results.get("fallback_used", False),
            reflection_rounds=rounds,
        )
```

---

## 五、Week 4: Supervisor + ForumHost

### 5.1 Supervisor

```python
# backend/orchestration/supervisor.py
import asyncio
from typing import Dict, List
from backend.agents.base import AgentOutput

class Supervisor:
    """多Agent调度器"""

    def __init__(self, agents: Dict[str, any]):
        self.agents = agents

    async def analyze(self, query: str, ticker: str) -> Dict[str, AgentOutput]:
        """并行调用所有Agent"""
        tasks = [
            self._call_agent(name, agent, query, ticker)
            for name, agent in self.agents.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs = {}
        for name, result in zip(self.agents.keys(), results):
            if isinstance(result, Exception):
                print(f"[Supervisor] {name} failed: {result}")
            else:
                outputs[name] = result

        return outputs

    async def _call_agent(self, name: str, agent, query: str, ticker: str) -> AgentOutput:
        return await agent.research(query, ticker)
```

### 5.2 ForumHost

```python
# backend/orchestration/forum.py
from dataclasses import dataclass
from typing import Dict, List
from backend.agents.base import AgentOutput

@dataclass
class ForumOutput:
    consensus: List[str]
    conflicts: List[str]
    recommendation: str
    confidence: float
    risks: List[str]

class ForumHost:
    """冲突消解 + 观点综合"""

    def __init__(self, llm=None):
        self.llm = llm

    async def synthesize(self, outputs: Dict[str, AgentOutput]) -> ForumOutput:
        """综合各Agent结果"""
        # 收集所有观点
        all_summaries = [f"[{name}]: {out.summary}" for name, out in outputs.items()]

        # 检测冲突
        conflicts = self._detect_conflicts(outputs)

        # 计算综合置信度
        confidences = [out.confidence for out in outputs.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        # 收集风险
        all_risks = []
        for out in outputs.values():
            all_risks.extend(out.risks)

        return ForumOutput(
            consensus=all_summaries,
            conflicts=conflicts,
            recommendation="HOLD",  # 默认，可用LLM生成
            confidence=avg_confidence,
            risks=list(set(all_risks))[:5],
        )

    def _detect_conflicts(self, outputs: Dict[str, AgentOutput]) -> List[str]:
        """检测观点冲突"""
        conflicts = []
        # 简单实现：检查置信度差异
        confidences = [(name, out.confidence) for name, out in outputs.items()]
        if len(confidences) >= 2:
            max_c = max(c for _, c in confidences)
            min_c = min(c for _, c in confidences)
            if max_c - min_c > 0.3:
                conflicts.append(f"置信度差异较大: {min_c:.2f} - {max_c:.2f}")
        return conflicts
```

---

## 六、验收标准

### 6.1 单元测试

```python
# backend/tests/test_agents.py
import pytest
from backend.agents.price_agent import PriceAgent
from backend.agents.news_agent import NewsAgent

@pytest.mark.asyncio
async def test_price_agent():
    agent = PriceAgent()
    # Mock orchestrator
    output = await agent.research("价格", "AAPL")
    assert output.agent_name == "PriceAgent"
    assert output.reflection_rounds == 0

@pytest.mark.asyncio
async def test_news_agent_reflection():
    agent = NewsAgent()
    output = await agent.research("新闻", "AAPL")
    assert output.agent_name == "NewsAgent"
    # 可能有反思轮数
```

### 6.2 集成测试

```python
# backend/tests/test_supervisor.py
@pytest.mark.asyncio
async def test_supervisor_parallel():
    supervisor = Supervisor({"price": PriceAgent(), "news": NewsAgent()})
    outputs = await supervisor.analyze("分析", "AAPL")
    assert len(outputs) >= 1
```

---

## 七、下一步

阶段1完成后，进入阶段2：
- IR Schema 定义
- DeepSearchAgent（按需触发）
- 前端结构化展示

详见 [04_CODE_EXAMPLES.md](./04_CODE_EXAMPLES.md)
