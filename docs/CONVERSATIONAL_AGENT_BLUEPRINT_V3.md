# 对话式股票分析 Agent 最终执行蓝图 (V3.0)

> **文档版本**: V3.0  
> **创建日期**: 2025-11-30  
> **目标**: 将 FinSight 从**单次报告生成器**升级为**对话式股票分析 Agent**

---

## 📋 目录

1. [愿景与目标](#愿景与目标)
2. [对原计划的质疑与建议](#对原计划的质疑与建议)
3. [核心架构设计](#核心架构设计)
4. [分阶段执行计划](#分阶段执行计划)
5. [SYSTEM_PROMPT 调整建议](#system_prompt-调整建议)
6. [最终执行清单](#最终执行清单)
7. [技术实现细节](#技术实现细节)

---

## 🎯 愿景与目标

### 当前状态
```
用户 → 单次查询 → 数据收集 → 完整报告 → 结束
```

### 目标状态
```
用户 → 意图识别 → 路由分发 ─┬→ 快速对话 (CHAT)     → 简洁回答
                           ├→ 深度报告 (REPORT)   → 专业分析
                           └→ 持续监控 (ALERT)    → 触发通知
                                     ↓
                              上下文记忆 (跨轮对话)
```

### 核心差异

| 维度 | 当前 (报告模式) | 目标 (对话模式) |
|------|----------------|----------------|
| **交互** | 单次问答 | 多轮对话，支持追问 |
| **响应** | 800+ 字完整报告 | 根据意图调整长度 |
| **上下文** | 无记忆 | 维护对话历史和用户偏好 |
| **数据获取** | 每次重新获取 | 智能缓存，增量更新 |
| **模式** | 固定流程 | 动态路由，多模式切换 |

---

## 🔍 对原计划的质疑与建议

### ✅ 原计划的优秀之处

1. **分阶段设计** - 从修复痛点到高级功能，优先级清晰
2. **多源回退机制** - 解决 API 限速的核心问题
3. **数据验证层** - 提高报告可信度
4. **量化分析强调** - 弥补当前报告的定量不足

### ⚠️ 需要质疑和调整的部分

#### 1. 监控模块：已有 LangSmith，无需重复建设

**原计划建议**: 
> 实现 `CostTracker`、监控仪表板、Prometheus + Grafana

**我的质疑**: 
您已经集成了 **LangSmith**，它提供了：
- ✅ 运行追踪和性能监控
- ✅ Token 使用量统计
- ✅ 工具调用链可视化
- ✅ 错误追踪和调试

**建议调整**:
```python
# ❌ 不需要重复建设
class CostTracker:  # 删除
class SimpleMonitor:  # 删除

# ✅ 充分利用现有 LangSmith
from langsmith_integration import start_run, log_event, finish_run

# 只需补充 LangSmith 未覆盖的：简易本地指标
class LocalMetrics:
    """轻量级本地指标（补充 LangSmith）"""
    def __init__(self):
        self.api_call_counts = defaultdict(int)
        self.cache_hits = 0
        self.cache_misses = 0
    
    def log_api_call(self, api_name: str, success: bool):
        self.api_call_counts[f"{api_name}_{success}"] += 1
```

**结论**: 将"监控仪表板"从阶段三移除，用 LangSmith 即可满足需求。

---

#### 2. 多 Agent 架构：当前阶段过度设计

**原计划建议**:
> 构建"数据收集 Agent"和"CIO 报告 Agent"的多 Agent 协作

**我的质疑**:
- 当前系统规模不需要多 Agent 复杂度
- LangChain 1.0 的单 Agent + 工具模式已足够
- 过早引入多 Agent 会增加调试难度

**建议调整**:
```
阶段一-二: 保持单 Agent + 强化工具层
阶段三+:  如果单 Agent 遇到性能瓶颈，再考虑拆分
```

**替代方案**: 使用 **ToolOrchestrator** 作为工具调度层，而非独立 Agent

---

#### 3. 情景模拟引擎：需要明确数据依赖

**原计划建议**:
> 实现 Monte Carlo 模拟和情景分析

**我的质疑**:
- Monte Carlo 需要历史波动率、分红率等数据
- 当前工具层不提供这些数据
- 没有数据支撑的"模拟"只是随机猜测

**建议调整**:
1. 先在阶段一添加 `get_financial_statements` 工具获取基础数据
2. 阶段三的情景模拟改为**基于规则的敏感性分析**，而非 Monte Carlo
3. 明确标注"简化模型，仅供参考"

---

#### 4. 对话模式缺失：这是最核心的遗漏

**原计划问题**:
原计划聚焦于**报告质量提升**，但忽略了**对话能力构建**：
- 没有意图识别 (Intent Classification)
- 没有对话上下文管理 (Context Management)  
- 没有追问/澄清机制 (Follow-up Handling)

**这是最大的差距，必须在阶段一解决。**

---

## 🏗️ 核心架构设计

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面层                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   CLI/REPL  │  │  Web API    │  │  未来: Chat UI          │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
└─────────┼────────────────┼─────────────────────┼────────────────┘
          └────────────────┼─────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    🧠 对话管理层 (新增)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                  ConversationRouter                        │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │ │
│  │  │ classify_   │  │ route_to_   │  │ ContextManager      │ │ │
│  │  │ intent()    │──│ handler()   │──│ (对话历史/偏好)      │ │ │
│  │  └─────────────┘  └──────┬──────┘  └─────────────────────┘ │ │
│  └──────────────────────────┼─────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              ▼
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    ┌───────────┐      ┌───────────┐       ┌───────────┐
    │   CHAT    │      │  REPORT   │       │   ALERT   │
    │  Handler  │      │  Handler  │       │  Handler  │
    │ (快速回答) │      │ (深度报告) │       │ (监控订阅) │
    └─────┬─────┘      └─────┬─────┘       └─────┬─────┘
          └──────────────────┼────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    🔧 工具编排层 (强化)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                  ToolOrchestrator                          │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │ │
│  │  │ DataCache   │  │ SourceRouter│  │ DataValidator       │ │ │
│  │  │ (智能缓存)   │──│ (多源回退)  │──│ (一致性校验)         │ │ │
│  │  └─────────────┘  └──────┬──────┘  └─────────────────────┘ │ │
│  └──────────────────────────┼─────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    📡 数据源层 (现有 + 扩展)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │
│  │ Alpha    │ │ Finnhub  │ │ yfinance │ │ Yahoo    │ │ DDG   │ │
│  │ Vantage  │ │          │ │          │ │ Scrape   │ │Search │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 核心模块说明

| 模块 | 职责 | 文件位置 |
|------|------|----------|
| `ConversationRouter` | 意图识别 + 模式路由 | `conversation/router.py` |
| `ContextManager` | 对话历史 + 用户偏好 | `conversation/context.py` |
| `ChatHandler` | 快速对话响应 | `handlers/chat_handler.py` |
| `ReportHandler` | 深度分析报告 | `handlers/report_handler.py` |
| `ToolOrchestrator` | 工具调度 + 缓存 + 验证 | `orchestration/orchestrator.py` |
| `DataCache` | 智能数据缓存 | `orchestration/cache.py` |
| `DataValidator` | 数据一致性校验 | `orchestration/validator.py` |

---

## 📅 分阶段执行计划

### 阶段一：可靠性与对话 MVP (5-7 天)

**目标**: 解决当前痛点 + 建立对话基础架构

#### 1.1 工具层可靠性 (Day 1-3)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 实现 `ToolOrchestrator` 多源回退 | `orchestration/orchestrator.py` | 5个测试股票 API 失败率 < 5% |
| 实现 `DataCache` 缓存层 | `orchestration/cache.py` | 相同查询命中率 > 90% |
| 新增 `get_financial_statements` | `tools.py` | 返回 P/E, 营收增长率, FCF |
| 强化现有工具的错误处理 | `tools.py` | 所有工具返回结构化错误 |

**ToolOrchestrator 核心代码骨架**:

```python
# orchestration/orchestrator.py

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio

@dataclass
class DataSource:
    """数据源定义"""
    name: str
    fetch_func: Callable
    priority: int  # 优先级，数字越小越优先
    rate_limit: int  # 每分钟请求限制
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0

class ToolOrchestrator:
    """工具编排器 - 负责数据源轮换、缓存和验证"""
    
    def __init__(self):
        self.cache = DataCache()
        self.sources: Dict[str, List[DataSource]] = {}
        self._init_sources()
    
    def _init_sources(self):
        """初始化数据源优先级映射"""
        self.sources = {
            'price': [
                DataSource('alpha_vantage', _fetch_alpha_vantage, 1, 5),
                DataSource('finnhub', _fetch_finnhub, 2, 60),
                DataSource('yfinance', _fetch_yfinance, 3, 30),
                DataSource('yahoo_scrape', _scrape_yahoo, 4, 10),
            ],
            'company_info': [
                DataSource('finnhub', _fetch_finnhub_profile, 1, 60),
                DataSource('alpha_vantage', _fetch_av_overview, 2, 5),
                DataSource('yfinance', _fetch_yf_info, 3, 30),
            ],
            # ... 其他数据类型
        }
    
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> Dict[str, Any]:
        """
        获取数据，带智能回退
        
        流程：缓存检查 → 按优先级尝试数据源 → 验证 → 返回
        """
        # 1. 检查缓存
        cache_key = f"{data_type}:{ticker}"
        cached = self.cache.get(cache_key)
        if cached:
            return {"data": cached, "source": "cache", "cached": True}
        
        # 2. 按优先级尝试数据源
        sources = self.sources.get(data_type, [])
        sources = sorted(sources, key=lambda s: (s.consecutive_failures, s.priority))
        
        for source in sources:
            try:
                result = await self._try_source(source, ticker, **kwargs)
                if result:
                    # 3. 验证数据
                    validated = self._validate(data_type, result)
                    if validated['is_valid']:
                        # 4. 更新缓存
                        self.cache.set(cache_key, result, ttl=self._get_ttl(data_type))
                        source.last_success = datetime.now()
                        source.consecutive_failures = 0
                        return {"data": result, "source": source.name, "cached": False}
                    else:
                        print(f"[Orchestrator] {source.name} 数据验证失败: {validated['issues']}")
            except Exception as e:
                source.consecutive_failures += 1
                print(f"[Orchestrator] {source.name} 失败: {e}")
                continue
        
        return {"data": None, "error": "所有数据源均失败", "tried_sources": [s.name for s in sources]}
    
    def _validate(self, data_type: str, data: Any) -> Dict[str, Any]:
        """数据验证 - 中间件模式"""
        # 调用 DataValidator
        from .validator import validate_data
        return validate_data(data_type, data)
    
    def _get_ttl(self, data_type: str) -> int:
        """获取缓存 TTL (秒)"""
        ttl_map = {
            'price': 60,           # 1分钟
            'company_info': 86400, # 24小时
            'news': 1800,          # 30分钟
            'financials': 86400,   # 24小时
            'sentiment': 3600,     # 1小时
        }
        return ttl_map.get(data_type, 300)
```

#### 1.2 对话基础架构 (Day 4-5)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 实现 `ConversationRouter` | `conversation/router.py` | 正确分类 CHAT/REPORT/ALERT |
| 实现 `ContextManager` | `conversation/context.py` | 保持 10 轮对话记忆 |
| 实现 `ChatHandler` 快速回答 | `handlers/chat_handler.py` | < 10秒响应简单问题 |

**意图分类核心逻辑**:

```python
# conversation/router.py

from enum import Enum
from typing import Tuple, Dict, Any
from langchain_core.messages import HumanMessage

class Intent(Enum):
    CHAT = "chat"           # 快速问答
    REPORT = "report"       # 深度报告
    ALERT = "alert"         # 监控订阅
    CLARIFY = "clarify"     # 需要澄清
    FOLLOWUP = "followup"   # 追问上文

class ConversationRouter:
    """对话路由器 - 负责意图识别和模式分发"""
    
    # 意图分类提示词 (关键!)
    CLASSIFICATION_PROMPT = """你是一个意图分类器。根据用户输入，判断其意图类型。

用户输入: "{query}"
对话历史: {history_summary}

意图类型:
- CHAT: 简单问题，需要快速简洁回答 (如："苹果股价多少？"、"市场今天怎么样？")
- REPORT: 需要深度分析报告 (如："分析AAPL"、"给我一份特斯拉投资报告"、"NVDA值得买吗？")
- ALERT: 想要设置监控/提醒 (如："帮我盯着AAPL"、"跌破100提醒我")
- FOLLOWUP: 追问上文内容 (如："为什么？"、"详细说说"、"风险呢？")
- CLARIFY: 输入模糊，需要澄清 (如："那个股票"、"它怎么样")

只返回一个词: CHAT / REPORT / ALERT / FOLLOWUP / CLARIFY"""

    def __init__(self, llm):
        self.llm = llm
        self.context_manager = ContextManager()
    
    def classify_intent(self, query: str) -> Tuple[Intent, Dict[str, Any]]:
        """
        分类用户意图
        
        Returns:
            (Intent, metadata) - 意图类型和提取的元数据
        """
        # 1. 规则快速匹配（避免调用 LLM）
        quick_intent = self._quick_match(query)
        if quick_intent:
            return quick_intent, self._extract_metadata(query)
        
        # 2. LLM 分类
        history_summary = self.context_manager.get_summary()
        prompt = self.CLASSIFICATION_PROMPT.format(
            query=query,
            history_summary=history_summary
        )
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        intent_str = response.content.strip().upper()
        
        try:
            intent = Intent(intent_str.lower())
        except ValueError:
            intent = Intent.CHAT  # 默认为对话模式
        
        return intent, self._extract_metadata(query)
    
    def _quick_match(self, query: str) -> Optional[Intent]:
        """规则快速匹配，避免简单问题调用 LLM"""
        query_lower = query.lower()
        
        # 报告关键词
        report_keywords = ['分析', '报告', 'analyze', 'report', '值得投资', '投资建议', '深度']
        if any(kw in query_lower for kw in report_keywords):
            return Intent.REPORT
        
        # 监控关键词
        alert_keywords = ['提醒', '监控', '盯着', 'alert', 'notify', '跌破', '涨到']
        if any(kw in query_lower for kw in alert_keywords):
            return Intent.ALERT
        
        # 追问关键词
        followup_keywords = ['为什么', '详细', '具体', '风险呢', '继续', 'why', 'more']
        if any(kw in query_lower for kw in followup_keywords):
            return Intent.FOLLOWUP
        
        # 简单价格查询
        price_patterns = ['多少钱', '股价', 'price', '现价']
        if any(p in query_lower for p in price_patterns):
            return Intent.CHAT
        
        return None  # 需要 LLM 判断
    
    def _extract_metadata(self, query: str) -> Dict[str, Any]:
        """从查询中提取元数据（股票代码、公司名等）"""
        import re
        
        metadata = {}
        
        # 提取股票代码 (大写字母 1-5 位)
        tickers = re.findall(r'\b[A-Z]{1,5}\b', query)
        if tickers:
            metadata['tickers'] = tickers
        
        # 提取公司名（简单匹配）
        company_map = {
            '苹果': 'AAPL', 'apple': 'AAPL',
            '特斯拉': 'TSLA', 'tesla': 'TSLA',
            '谷歌': 'GOOGL', 'google': 'GOOGL',
            '微软': 'MSFT', 'microsoft': 'MSFT',
            '英伟达': 'NVDA', 'nvidia': 'NVDA',
        }
        for name, ticker in company_map.items():
            if name in query.lower():
                metadata.setdefault('tickers', []).append(ticker)
        
        return metadata
    
    def route(self, query: str):
        """路由到对应处理器"""
        intent, metadata = self.classify_intent(query)
        
        # 更新上下文
        self.context_manager.add_turn(query, intent)
        
        handlers = {
            Intent.CHAT: self._handle_chat,
            Intent.REPORT: self._handle_report,
            Intent.ALERT: self._handle_alert,
            Intent.FOLLOWUP: self._handle_followup,
            Intent.CLARIFY: self._handle_clarify,
        }
        
        handler = handlers.get(intent, self._handle_chat)
        return handler(query, metadata)
```

#### 1.3 提示词重构 (Day 6)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 拆分 SYSTEM_PROMPT 为多模式 | `prompts/` | 3 套提示词：CHAT/REPORT/ALERT |
| 增加数据容错指令 | `prompts/report_prompt.py` | Agent 能处理部分工具失败 |
| 增加量化分析要求 | `prompts/report_prompt.py` | 报告必含估值指标 |

#### 1.4 冒烟测试 (Day 7)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 编写核心冒烟测试 | `tests/smoke_test.py` | 5 个代表性股票全部通过 |
| 意图分类测试 | `tests/test_router.py` | 10 个测试用例准确率 > 90% |

```python
# tests/smoke_test.py

import pytest
from conversation.router import ConversationRouter, Intent

class TestIntentClassification:
    """意图分类冒烟测试"""
    
    @pytest.fixture
    def router(self):
        from langchain_agent import create_financial_agent
        agent = create_financial_agent()
        return ConversationRouter(agent.llm)
    
    @pytest.mark.parametrize("query,expected", [
        ("AAPL 股价多少？", Intent.CHAT),
        ("分析苹果公司股票", Intent.REPORT),
        ("给我一份特斯拉投资报告", Intent.REPORT),
        ("帮我盯着 NVDA，跌破 100 提醒我", Intent.ALERT),
        ("为什么你这么说？", Intent.FOLLOWUP),
        ("市场今天怎么样", Intent.CHAT),
    ])
    def test_intent_classification(self, router, query, expected):
        intent, _ = router.classify_intent(query)
        assert intent == expected, f"Query: {query}, Expected: {expected}, Got: {intent}"


class TestCorePipeline:
    """核心管道冒烟测试"""
    
    TEST_TICKERS = ['AAPL', 'GOOGL', 'TSLA', 'SPY', 'BABA']
    
    @pytest.mark.parametrize("ticker", TEST_TICKERS)
    def test_price_fetch(self, ticker):
        from tools import get_stock_price
        result = get_stock_price(ticker)
        assert "Error" not in result, f"{ticker} 价格获取失败: {result}"
        assert "$" in result, f"{ticker} 价格格式异常: {result}"
    
    @pytest.mark.parametrize("ticker", TEST_TICKERS)
    def test_full_analysis(self, ticker):
        from langchain_agent import create_financial_agent
        agent = create_financial_agent()
        result = agent.analyze(f"简要分析 {ticker}")
        assert result['success'], f"{ticker} 分析失败: {result.get('error')}"
        assert len(result.get('output', '')) > 200, f"{ticker} 报告过短"
```

---

### 阶段二：对话增强与数据深度 (2 周)

**目标**: 完善对话体验 + 提升分析深度

#### 2.1 对话能力增强 (Week 1)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 实现多轮对话支持 | `conversation/context.py` | 支持追问和澄清 |
| 实现 `FollowupHandler` | `handlers/followup_handler.py` | 能理解"为什么"类追问 |
| 对话历史摘要 | `conversation/context.py` | 超过 10 轮自动摘要 |

**上下文管理器实现**:

```python
# conversation/context.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import deque

@dataclass
class ConversationTurn:
    """对话轮次"""
    query: str
    intent: str
    response: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class ContextManager:
    """对话上下文管理器"""
    
    def __init__(self, max_turns: int = 10, max_tokens: int = 4000):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.history: deque = deque(maxlen=max_turns)
        self.current_focus: Optional[str] = None  # 当前关注的股票
        self.user_preferences: Dict[str, Any] = {}
        self.accumulated_data: Dict[str, Any] = {}  # 已收集的数据
    
    def add_turn(self, query: str, intent: str, response: str = None, metadata: dict = None):
        """添加对话轮次"""
        turn = ConversationTurn(
            query=query,
            intent=intent,
            response=response,
            metadata=metadata or {}
        )
        self.history.append(turn)
        
        # 更新关注焦点
        if metadata and 'tickers' in metadata:
            self.current_focus = metadata['tickers'][0]
    
    def get_summary(self) -> str:
        """获取对话历史摘要"""
        if not self.history:
            return "无历史对话"
        
        recent = list(self.history)[-5:]  # 最近 5 轮
        summary = []
        for turn in recent:
            summary.append(f"- 用户({turn.intent}): {turn.query[:50]}...")
            if turn.response:
                summary.append(f"  助手: {turn.response[:100]}...")
        
        focus_info = f"\n当前焦点: {self.current_focus}" if self.current_focus else ""
        return "\n".join(summary) + focus_info
    
    def get_context_for_llm(self) -> List[Dict[str, str]]:
        """获取 LLM 可用的上下文消息列表"""
        messages = []
        for turn in self.history:
            messages.append({"role": "user", "content": turn.query})
            if turn.response:
                messages.append({"role": "assistant", "content": turn.response})
        return messages
    
    def resolve_reference(self, query: str) -> str:
        """解析指代词 (如"它"、"那个股票")"""
        pronouns = ['它', '那个', '这个', 'it', 'that']
        if any(p in query.lower() for p in pronouns):
            if self.current_focus:
                # 替换指代词
                for p in pronouns:
                    query = query.replace(p, self.current_focus)
        return query
    
    def cache_data(self, key: str, data: Any):
        """缓存分析过程中获取的数据"""
        self.accumulated_data[key] = {
            'data': data,
            'timestamp': datetime.now()
        }
    
    def get_cached_data(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if key in self.accumulated_data:
            cached = self.accumulated_data[key]
            # 5 分钟内有效
            if (datetime.now() - cached['timestamp']).seconds < 300:
                return cached['data']
        return None
```

#### 2.2 数据深度增强 (Week 2)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 新增 `get_technical_indicators` | `tools.py` | 返回 RSI, MACD, SMA |
| 实现 `DataValidator` 中间件 | `orchestration/validator.py` | 检测异常数据 |
| 数据新鲜度追踪 | `orchestration/freshness.py` | 标注数据时效 |

**数据验证中间件**:

```python
# orchestration/validator.py

from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class ValidationResult:
    is_valid: bool
    confidence: float  # 0-1
    issues: List[str]
    warnings: List[str]

def validate_data(data_type: str, data: Any) -> ValidationResult:
    """
    数据验证中间件
    在工具返回数据后、传给 LLM 前执行
    """
    validators = {
        'price': _validate_price,
        'company_info': _validate_company_info,
        'financials': _validate_financials,
    }
    
    validator = validators.get(data_type, _validate_generic)
    return validator(data)

def _validate_price(data: Dict) -> ValidationResult:
    """验证股价数据"""
    issues = []
    warnings = []
    
    # 检查必要字段
    if 'price' not in data:
        issues.append("缺少价格字段")
    
    # 检查合理范围
    price = data.get('price', 0)
    if price <= 0:
        issues.append(f"价格异常: {price}")
    elif price > 100000:
        warnings.append(f"股价异常高: ${price}，请核实")
    
    # 检查涨跌幅合理性
    change_pct = data.get('change_percent', 0)
    if abs(change_pct) > 20:
        warnings.append(f"涨跌幅异常: {change_pct}%，可能是熔断或数据错误")
    
    return ValidationResult(
        is_valid=len(issues) == 0,
        confidence=1.0 if not issues and not warnings else 0.7,
        issues=issues,
        warnings=warnings
    )

def _validate_financials(data: Dict) -> ValidationResult:
    """验证财务数据"""
    issues = []
    warnings = []
    
    # 检查 P/E 合理性
    pe = data.get('pe_ratio')
    if pe is not None:
        if pe < 0:
            warnings.append(f"P/E 为负 ({pe})，公司可能亏损")
        elif pe > 200:
            warnings.append(f"P/E 异常高 ({pe})，可能是成长股或数据异常")
    
    # 交叉验证：市值 ≈ 股价 × 股数
    market_cap = data.get('market_cap')
    shares = data.get('shares_outstanding')
    price = data.get('price')
    
    if all([market_cap, shares, price]):
        calculated_cap = price * shares
        diff = abs(market_cap - calculated_cap) / market_cap
        if diff > 0.1:  # 10% 误差
            issues.append(f"市值数据不一致: 报告 {market_cap:,}, 计算 {calculated_cap:,.0f}")
    
    return ValidationResult(
        is_valid=len(issues) == 0,
        confidence=0.9 if not warnings else 0.7,
        issues=issues,
        warnings=warnings
    )
```

---

### 阶段三：智能化与专业化 (3-4 周)

**目标**: 提升分析智能度 + 专业功能

#### 3.1 智能工具选择 (Week 1)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 实现 `IntelligentToolSequencer` | `orchestration/sequencer.py` | 根据意图选择工具子集 |
| 优化工具调用顺序 | `orchestration/sequencer.py` | 减少 30% 冗余调用 |

```python
# orchestration/sequencer.py

class IntelligentToolSequencer:
    """根据查询意图智能规划工具序列"""
    
    # 工具集定义
    TOOL_SETS = {
        'quick_price': ['get_current_datetime', 'get_stock_price'],
        'quick_overview': ['get_current_datetime', 'get_stock_price', 'get_company_info'],
        'valuation_focus': ['get_current_datetime', 'get_stock_price', 'get_financial_statements', 'get_performance_comparison'],
        'news_focus': ['get_current_datetime', 'get_company_news', 'get_market_sentiment', 'search'],
        'full_analysis': ['get_current_datetime', 'search', 'get_stock_price', 'get_company_info', 
                         'get_company_news', 'get_market_sentiment', 'get_financial_statements',
                         'get_performance_comparison', 'analyze_historical_drawdowns'],
    }
    
    def plan_sequence(self, query: str, intent: str) -> List[str]:
        """规划工具调用序列"""
        query_lower = query.lower()
        
        # 快速价格查询
        if intent == 'chat' and any(kw in query_lower for kw in ['价格', 'price', '多少钱']):
            return self.TOOL_SETS['quick_price']
        
        # 估值聚焦
        if any(kw in query_lower for kw in ['估值', 'valuation', 'pe', '值得']):
            return self.TOOL_SETS['valuation_focus']
        
        # 新闻聚焦
        if any(kw in query_lower for kw in ['新闻', 'news', '发生了什么', '最近']):
            return self.TOOL_SETS['news_focus']
        
        # 完整报告
        if intent == 'report':
            return self.TOOL_SETS['full_analysis']
        
        # 默认概览
        return self.TOOL_SETS['quick_overview']
```

#### 3.2 用户画像适配 (Week 2)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 定义用户画像 | `user/profiles.py` | 3 种画像：专业/进阶/入门 |
| 报告风格适配 | `handlers/report_handler.py` | 根据画像调整术语和深度 |

#### 3.3 基础情景分析 (Week 3)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 实现敏感性分析 | `analysis/scenarios.py` | 基于规则的牛/熊目标价 |
| 风险量化 | `analysis/risk.py` | 输出 VaR 和最大回撤估计 |

#### 3.4 自动化测试 (Week 4)

| 任务 | 关联文件 | 验收标准 |
|------|----------|----------|
| 完整单元测试 | `tests/` | 覆盖率 > 60% |
| 集成测试 | `tests/integration/` | 端到端流程验证 |
| 报告质量评估 | `tests/quality/` | 自动评分系统 |

---

## 📝 SYSTEM_PROMPT 调整建议

### 当前问题

1. **单一模式**: 只有一套报告生成提示词
2. **无容错指导**: 工具失败时缺乏处理指令
3. **量化要求弱**: 缺少强制估值指标要求

### 建议拆分为多套提示词

#### 1. CHAT_PROMPT (快速对话)

```python
CHAT_PROMPT = """你是一位友好的金融分析助手。回答要简洁、直接、有用。

当前日期: {current_date}
对话历史: {context_summary}

用户问题: {query}

回答规则:
1. 简洁为主 - 通常 2-5 句话即可
2. 如果需要调用工具获取数据，只调用必要的工具
3. 如果是简单问题（如股价查询），直接返回数据
4. 如果检测到用户可能需要深度分析，提示："需要我生成详细的分析报告吗？"

可用工具:
{tools_short_list}

回答格式:
直接给出答案，不需要冗长的报告结构。"""
```

#### 2. REPORT_PROMPT (深度报告) - 增强版

```python
REPORT_PROMPT = """你是一位顶级对冲基金的首席投资官(CIO)。你的任务是生成全面、专业、可操作的投资报告。

当前日期: {current_date}
用户查询: {query}
已收集数据: {accumulated_data}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 关键规则（必须遵守）:

1. **数据容错**: 
   - 如果某个工具失败，使用 search 工具获取替代数据
   - 在报告中标注数据来源（API/搜索/估算）
   - 缺失的数据必须明确说明，不能编造

2. **量化要求 (MANDATORY)**:
   - 必须包含: 当前股价、涨跌幅、市值
   - 估值指标: P/E ratio 或说明为何不适用
   - 历史对比: YTD 收益率、1年收益率
   - 风险量化: 历史最大回撤或波动率估计

3. **结构完整性**:
   所有以下章节必须存在且有实质内容:
   
   ## 执行摘要 (EXECUTIVE SUMMARY)
   - 明确的 BUY/HOLD/SELL 建议
   - 置信度: 高/中/低
   - 1-2 句话核心理由

   ## 当前市场状况 (CURRENT POSITION)
   - 股价: $XXX
   - 涨跌: +X.XX% (今日)
   - YTD: +XX%
   - 市值: $XXX B

   ## 估值分析 (VALUATION) ⭐新增
   - P/E: XX (历史中位数: XX)
   - P/S, EV/EBITDA (如有)
   - 与同行对比

   ## 宏观与催化剂 (MACRO & CATALYSTS)
   - 当前经济环境
   - 关键日期（财报、FOMC等）

   ## 风险评估 (RISK ASSESSMENT)
   - 历史最大回撤: -XX%
   - 主要风险因素（量化描述）
   - 最坏情景

   ## 投资策略 (STRATEGY)
   - 入场点位
   - 止损位
   - 目标价（牛/熊/基准）

   ## 数据声明 (DATA DISCLAIMER) ⭐新增
   - 使用的数据源
   - 数据时效
   - 分析局限性

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
可用工具:
{tools}

开始分析。"""
```

#### 3. ALERT_PROMPT (监控订阅)

```python
ALERT_PROMPT = """你是一位金融监控助手。帮助用户设置股票价格或事件提醒。

用户请求: {query}

提取信息:
1. 股票代码/名称
2. 触发条件（如：跌破 $100、涨幅超过 5%）
3. 通知方式（默认：下次对话时提醒）

确认格式:
"已设置监控：当 [股票] [条件] 时，将提醒您。当前价格：$XXX"

注意:
- 如果条件不清晰，主动询问
- 告知当前价格供参考
- 说明监控的局限性（非实时）"""
```

---

## ✅ 最终执行清单

### 阶段一完成标准 (第 1 周末检查)

- [ ] `ToolOrchestrator` 实现，5 个测试股票 API 失败率 < 5%
- [ ] `DataCache` 实现，相同查询命中率 > 90%
- [ ] `ConversationRouter` 实现，意图分类准确率 > 85%
- [ ] `ContextManager` 实现，支持 10 轮对话记忆
- [ ] `ChatHandler` 实现，简单问题 < 10 秒响应
- [ ] 3 套 SYSTEM_PROMPT 完成（CHAT/REPORT/ALERT）
- [ ] 冒烟测试全部通过

### 阶段二完成标准 (第 3 周末检查)

- [ ] 多轮对话追问功能正常
- [ ] `get_technical_indicators` 工具实现
- [ ] `DataValidator` 中间件部署
- [ ] 数据新鲜度标注功能
- [ ] 指代词解析（"它"→ 当前焦点股票）

### 阶段三完成标准 (第 6 周末检查)

- [ ] `IntelligentToolSequencer` 实现，减少 30% 冗余调用
- [ ] 3 种用户画像适配
- [ ] 基础情景分析（敏感性分析）
- [ ] 单元测试覆盖率 > 60%

---

## 🔧 技术实现细节

### 目录结构调整

```
FinSight/
├── agent.py                 # 保留，兼容旧版
├── langchain_agent.py       # 保留，LangChain 集成
├── tools.py                 # 保留，扩展工具
├── config.py                # 保留
├── main.py                  # 更新，支持对话模式
│
├── conversation/            # 🆕 对话管理层
│   ├── __init__.py
│   ├── router.py           # 意图路由
│   └── context.py          # 上下文管理
│
├── handlers/               # 🆕 模式处理器
│   ├── __init__.py
│   ├── chat_handler.py     # 快速对话
│   ├── report_handler.py   # 深度报告
│   ├── alert_handler.py    # 监控订阅
│   └── followup_handler.py # 追问处理
│
├── orchestration/          # 🆕 工具编排层
│   ├── __init__.py
│   ├── orchestrator.py     # 核心编排器
│   ├── cache.py            # 数据缓存
│   ├── validator.py        # 数据验证
│   ├── sequencer.py        # 工具序列规划
│   └── freshness.py        # 数据新鲜度
│
├── prompts/                # 🆕 提示词模板
│   ├── __init__.py
│   ├── chat_prompt.py
│   ├── report_prompt.py
│   └── alert_prompt.py
│
├── analysis/               # 🆕 分析模块
│   ├── __init__.py
│   ├── scenarios.py        # 情景分析
│   └── risk.py             # 风险量化
│
├── user/                   # 🆕 用户管理
│   ├── __init__.py
│   └── profiles.py         # 用户画像
│
└── tests/                  # 🆕 测试套件
    ├── __init__.py
    ├── smoke_test.py
    ├── test_router.py
    ├── test_cache.py
    └── test_validator.py
```

### 技术选型说明

| 组件 | 选型 | 理由 |
|------|------|------|
| 缓存 | 内存字典 + TTL | 简单场景无需 Redis |
| 对话历史 | Python deque | 固定长度，自动淘汰旧数据 |
| 意图分类 | 规则 + LLM 混合 | 简单场景用规则，复杂场景用 LLM |
| 监控 | LangSmith | 已集成，无需重复建设 |
| 测试 | pytest | Python 标准选择 |

---

## 📌 总结

本蓝图的核心理念：

1. **对话优先**: 将 FinSight 从报告生成器转变为对话式助手
2. **渐进增强**: 分三阶段实施，每阶段有明确交付物
3. **不过度设计**: 避免多 Agent 复杂架构，先做好单 Agent
4. **利用现有**: 充分利用 LangSmith 监控，不重复造轮子
5. **可测试**: 每阶段都有冒烟测试和验收标准

**预计总工期**: 6 周  
**阶段一 MVP**: 1 周可交付对话基础能力

---

*文档作者: Claude (Cursor AI Assistant)*  
*最后更新: 2025-11-30*

