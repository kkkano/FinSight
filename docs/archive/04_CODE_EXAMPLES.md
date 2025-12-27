# 核心代码示例

> 📅 更新日期: 2025-12-27
> 🎯 可直接复制使用的代码片段

---

## 一、agents/__init__.py

```python
# backend/agents/__init__.py
from .base import BaseFinancialAgent, AgentOutput, Evidence
from .price_agent import PriceAgent
from .news_agent import NewsAgent

__all__ = [
    "BaseFinancialAgent",
    "AgentOutput",
    "Evidence",
    "PriceAgent",
    "NewsAgent",
]
```

---

## 二、LangGraph 反思循环模式

```python
# 标准反思循环实现
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, List, Annotated
from langgraph.graph.message import add_messages

class ReflectionState(TypedDict):
    messages: Annotated[List, add_messages]
    summary: str
    gaps: List[str]
    iteration: int

async def search_node(state: ReflectionState) -> dict:
    """初始/补充搜索"""
    # 执行搜索逻辑
    return {"summary": "搜索结果..."}

async def reflect_node(state: ReflectionState) -> dict:
    """反思：识别知识空白"""
    summary = state["summary"]
    # LLM 识别空白
    gaps = []  # await llm.identify_gaps(summary)
    return {"gaps": gaps, "iteration": state["iteration"] + 1}

def should_continue(state: ReflectionState) -> str:
    if not state["gaps"] or state["iteration"] >= 3:
        return "end"
    return "search"

def build_reflection_graph():
    g = StateGraph(ReflectionState)
    g.add_node("search", search_node)
    g.add_node("reflect", reflect_node)
    g.add_edge(START, "search")
    g.add_edge("search", "reflect")
    g.add_conditional_edges("reflect", should_continue, {"search": "search", "end": END})
    return g.compile()
```

---

## 三、Supervisor 并行调度

```python
# backend/orchestration/supervisor.py
import asyncio
from typing import Dict
from backend.agents.base import AgentOutput

class Supervisor:
    def __init__(self, agents: Dict[str, any]):
        self.agents = agents

    async def analyze(self, query: str, ticker: str) -> Dict[str, AgentOutput]:
        tasks = [
            self._safe_call(name, agent, query, ticker)
            for name, agent in self.agents.items()
        ]
        results = await asyncio.gather(*tasks)
        return {name: r for name, r in zip(self.agents.keys(), results) if r}

    async def _safe_call(self, name, agent, query, ticker):
        try:
            return await agent.research(query, ticker)
        except Exception as e:
            print(f"[Supervisor] {name} error: {e}")
            return None
```

---

## 四、ForumHost 冲突消解

```python
# backend/orchestration/forum.py
from dataclasses import dataclass
from typing import Dict, List
from backend.agents.base import AgentOutput

@dataclass
class ForumOutput:
    consensus: List[str]
    conflicts: List[str]
    recommendation: str  # BUY/HOLD/SELL
    confidence: float
    risks: List[str]

class ForumHost:
    PROMPT = """综合以下分析结果：
{agent_outputs}

输出：
1. 共识观点
2. 分歧观点
3. 投资建议（BUY/HOLD/SELL）
4. 置信度（0-1）
5. 风险因素"""

    def __init__(self, llm=None):
        self.llm = llm

    async def synthesize(self, outputs: Dict[str, AgentOutput]) -> ForumOutput:
        summaries = [f"[{k}]: {v.summary}" for k, v in outputs.items()]
        confidences = [v.confidence for v in outputs.values()]
        risks = []
        for v in outputs.values():
            risks.extend(v.risks)

        return ForumOutput(
            consensus=summaries,
            conflicts=self._detect_conflicts(outputs),
            recommendation="HOLD",
            confidence=sum(confidences) / len(confidences) if confidences else 0.5,
            risks=list(set(risks))[:5],
        )

    def _detect_conflicts(self, outputs) -> List[str]:
        # 简单实现：检查置信度差异
        cs = [v.confidence for v in outputs.values()]
        if cs and max(cs) - min(cs) > 0.3:
            return [f"置信度差异: {min(cs):.2f}-{max(cs):.2f}"]
        return []
```

---

## 五、IR Schema (阶段2)

```python
# backend/report/ir.py
from pydantic import BaseModel, validator
from typing import List, Optional
from datetime import datetime

class Evidence(BaseModel):
    text: str
    source: str
    url: Optional[str] = None
    confidence: float = 0.8

class Section(BaseModel):
    title: str
    content: str
    key_points: List[str]
    evidence: List[Evidence]
    agent_source: str

class ReportIR(BaseModel):
    ticker: str
    title: str
    generated_at: datetime
    executive_summary: str
    recommendation: str  # BUY/HOLD/SELL
    confidence: float
    sections: List[Section]
    risks: List[str]
    data_sources: List[str]

    @validator('confidence')
    def check_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('confidence must be 0-1')
        return v

    @validator('sections')
    def check_sections(cls, v):
        if len(v) < 2:
            raise ValueError('at least 2 sections required')
        return v

class IRRenderer:
    def to_markdown(self, ir: ReportIR) -> str:
        lines = [f"# {ir.title}", f"*{ir.generated_at}*", "", ir.executive_summary, ""]
        for s in ir.sections:
            lines.append(f"## {s.title}")
            lines.append(s.content)
        lines.append(f"\n**建议**: {ir.recommendation} (置信度: {ir.confidence:.0%})")
        return "\n".join(lines)
```

---

## 六、测试示例

```python
# backend/tests/test_agents.py
import pytest
from backend.agents.price_agent import PriceAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.base import AgentOutput

@pytest.mark.asyncio
async def test_price_agent_output_format():
    agent = PriceAgent()
    output = await agent.research("价格", "AAPL")

    assert isinstance(output, AgentOutput)
    assert output.agent_name == "PriceAgent"
    assert output.reflection_rounds == 0
    assert 0 <= output.confidence <= 1

@pytest.mark.asyncio
async def test_news_agent_has_reflection():
    agent = NewsAgent()
    output = await agent.research("新闻", "AAPL")

    assert output.agent_name == "NewsAgent"
    # NewsAgent 可能有反思轮数
    assert output.reflection_rounds >= 0

# backend/tests/test_supervisor.py
@pytest.mark.asyncio
async def test_supervisor_parallel_execution():
    from backend.orchestration.supervisor import Supervisor

    supervisor = Supervisor({
        "price": PriceAgent(),
        "news": NewsAgent(),
    })

    outputs = await supervisor.analyze("分析", "AAPL")

    assert len(outputs) >= 1
    for name, output in outputs.items():
        assert isinstance(output, AgentOutput)
```

---

## 七、集成到现有系统

```python
# backend/conversation/agent.py 中添加

# 在 __init__ 中初始化
from backend.agents import PriceAgent, NewsAgent
from backend.orchestration.supervisor import Supervisor
from backend.orchestration.forum import ForumHost

class ConversationAgent:
    def __init__(self, ...):
        # ... 现有代码 ...

        # 新增：多Agent支持
        self.multi_agent_enabled = os.getenv("MULTI_AGENT_ENABLED", "false").lower() == "true"
        if self.multi_agent_enabled:
            self.supervisor = Supervisor({
                "price": PriceAgent(orchestrator=self.orchestrator),
                "news": NewsAgent(orchestrator=self.orchestrator),
            })
            self.forum = ForumHost(llm=self.llm)

    async def _handle_chat_multi_agent(self, query: str, metadata: dict):
        """多Agent处理"""
        ticker = metadata.get("tickers", [None])[0]
        if not ticker:
            return self._handle_chat(query, metadata)

        outputs = await self.supervisor.analyze(query, ticker)
        forum_result = await self.forum.synthesize(outputs)

        return {
            "success": True,
            "response": self._format_forum_output(forum_result),
            "agent_outputs": {k: v.to_dict() for k, v in outputs.items()},
        }
```

---

## 八、环境变量配置

```env
# .env 新增配置

# 多Agent开关
MULTI_AGENT_ENABLED=false

# 反思循环配置
MAX_REFLECTIONS=2
NEWS_AGENT_TTL=600
PRICE_AGENT_TTL=30

# ForumHost
FORUM_CONFLICT_THRESHOLD=0.3
```
