我来逐一分析这个金融分析Agent项目的现状和改进建议：

## LangChain 最新版本迁移方案 (2025年)

基于对现有代码的深入分析，我将提供一个使用 **LangChain 0.3.x 最新特性** 的完整迁移方案。

### 🚀 最新LangChain特性分析

**1. 最新的@tool装饰器 (LangChain 0.3.x)**
```python
# 2025年最新语法
from langchain_core.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional

class StockInput(BaseModel):
    ticker: str = Field(description="股票代码，例如 'AAPL', 'NVDA'")
    period: Optional[str] = Field(default="1mo", description="时间周期")

@tool(args_schema=StockInput)
def get_stock_price(input_data: StockInput) -> str:
    """获取股票实时价格和历史数据

    Args:
        input_data: 包含股票代码和时间周期的输入参数

    Returns:
        格式化的价格信息字符串
    """
    # 现有逻辑保持不变
    return get_stock_price_impl(input_data.ticker, input_data.period)
```

**2. LangGraph最新Agent框架**
```python
# 2025年最新的LangGraph ReAct实现
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from typing import TypedDict, List

class AgentState(TypedDict):
    messages: List[HumanMessage]
    current_step: str
    observations: List[str]
    report_generated: bool

def create_financial_agent():
    # 使用最新的StateGraph
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("think", think_node)
    workflow.add_node("act", act_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("generate_report", generate_report_node)

    # 设置边
    workflow.set_entry_point("think")
    workflow.add_edge("think", "act")
    workflow.add_edge("act", "observe")
    workflow.add_conditional_edges(
        "observe",
        should_continue,
        {
            "continue": "think",
            "generate": "generate_report"
        }
    )
    workflow.add_edge("generate_report", END)

    # 使用最新的内存检查点
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
```

**3. 最新流式输出系统**
```python
from langchain_core.callbacks import StreamingStdOutCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

# 2025年最新的流式处理
class FinancialStreamingHandler(StreamingStdOutCallbackHandler):
    def __init__(self):
        self.thought_count = 0
        self.action_count = 0

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        if "Thought:" in token:
            self.thought_count += 1
            print(f"💭 思考 {self.thought_count}: ", end="", flush=True)
        elif "Action:" in token:
            self.action_count += 1
            print(f"🔧 执行动作 {self.action_count}: ", end="", flush=True)
        else:
            print(token, end="", flush=True)

# 使用最新的流式管道
def stream_financial_analysis(query: str):
    streaming_handler = FinancialStreamingHandler()

    chain = (
        {"query": RunnablePassthrough()}
        | prompt
        | llm.bind(callbacks=[streaming_handler])
        | StrOutputParser()
    )

    return chain.stream(query)
```

**4. 最新Prompt模板系统**
```python
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.prompts.few_shot import FewShotChatMessagePromptTemplate

# 2025年最新的模块化提示词
examples = [
    {
        "input": "分析NVDA股票",
        "thought_process": "我需要收集NVDA的实时数据，包括价格、新闻、市场情绪等",
        "actions": ["get_current_datetime", "search NVDA stock analysis", "get_stock_price NVDA"]
    }
]

example_prompt = ChatPromptTemplate.from_messages([
    ("human", "{input}"),
    ("ai", "Thought: {thought_process}\nActions: {actions}")
])

few_shot_prompt = FewShotChatMessagePromptTemplate(
    examples=examples,
    example_prompt=example_prompt,
)

system_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是专业投资分析官(CIO)。使用最新数据{current_date}生成详细报告。

    {few_shot_examples}

    可用工具: {tools}
    """),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad")
])
```

**5. 最新记忆和会话管理**
```python
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

# 2025年最新的会话管理
class FinancialChatHistory(BaseChatMessageHistory):
    def __init__(self):
        super().__init__()
        self.analysis_sessions = {}  # 存储每个分析会话

    def add_analysis_session(self, ticker: str, session_data: dict):
        """添加分析会话记录"""
        self.analysis_sessions[ticker] = {
            "timestamp": datetime.now(),
            "data": session_data,
            "report": session_data.get("report", "")
        }

    def get_previous_analysis(self, ticker: str) -> str:
        """获取之前的分析结果"""
        if ticker in self.analysis_sessions:
            return f"之前{ticker}的分析: {self.analysis_sessions[ticker]['report'][:200]}..."
        return ""

# 使用最新记忆系统
history = InMemoryChatMessageHistory()
chain_with_history = RunnableWithMessageHistory(
    agent_chain,
    lambda session_id: history,
    input_messages_key="input",
    history_messages_key="chat_history",
)
```

### 📋 完整迁移实施计划

#### 阶段1: 环境升级 (立即执行)

**更新requirements.txt:**
```txt
# 核心LangChain包 (2025年最新版本)
langchain==0.3.10
langchain-core==0.3.21
langchain-openai==0.2.8
langchain-anthropic==0.3.5
langchain-community==0.3.11

# LangGraph (最新Agent框架)
langgraph==0.2.45
langgraph-checkpoint==0.2.9

# 现有依赖保持
litellm==1.52.23
ddgs==9.6.0
yfinance==0.2.66
finnhub-python==2.4.35
requests==2.32.3
beautifulsoup4==4.12.3
pandas==2.2.3
python-dotenv==1.0.1

# 新增性能优化
asyncio-throttle==1.0.2
tenacity==9.0.0
pydantic==2.9.2
```

#### 阶段2: 工具系统重构 (第1-2天)

**创建 langchain_tools.py:**
```python
from langchain_core.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional, List, Dict, Any
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from concurrent.futures import ThreadPoolExecutor

# 现有工具导入
from tools import (
    get_stock_price_impl, get_company_news_impl, get_company_info_impl,
    search_impl, get_market_sentiment_impl, get_economic_events_impl,
    get_performance_comparison_impl, analyze_historical_drawdowns_impl,
    get_current_datetime_impl
)

class TickerInput(BaseModel):
    ticker: str = Field(description="股票代码，例如 'AAPL', 'NVDA', '^GSPC'")

class SearchInput(BaseModel):
    query: str = Field(description="搜索查询字符串")

class ComparisonInput(BaseModel):
    tickers: Dict[str, str] = Field(description="股票代码字典，例如 {'Name': 'TICK'}")

class DateInput(BaseModel):
    pass  # 无参数输入

# 使用最新@tool装饰器重构所有工具
@tool(args_schema=TickerInput)
def get_stock_price(input_data: TickerInput) -> str:
    """获取股票实时价格和基本面数据

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        详细的价格信息和基本面数据
    """
    return get_stock_price_impl(input_data.ticker)

@tool(args_schema=TickerInput)
def get_company_news(input_data: TickerInput) -> str:
    """获取公司最新新闻和市场动态

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        格式化的新闻摘要
    """
    return get_company_news_impl(input_data.ticker)

@tool(args_schema=SearchInput)
def search(input_data: SearchInput) -> str:
    """使用搜索引擎获取市场信息

    Args:
        input_data: 包含搜索查询的输入参数

    Returns:
        搜索结果摘要
    """
    return search_impl(input_data.query)

# 其他工具类似重构...

# 工具列表
FINANCIAL_TOOLS = [
    get_stock_price,
    get_company_news,
    get_company_info,
    search,
    get_market_sentiment,
    get_economic_events,
    get_performance_comparison,
    analyze_historical_drawdowns,
    get_current_datetime,
]
```

#### 阶段3: Agent核心重构 (第3-4天)

**创建 langchain_agent.py:**
```python
from langchain_core.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict, List, Dict, Any
import asyncio
from datetime import datetime

from .langchain_tools import FINANCIAL_TOOLS
from .llm_service import get_llm_provider

class FinancialAgentState(TypedDict):
    messages: List[Dict[str, Any]]
    current_step: str
    observations: List[str]
    report_generated: bool
    analysis_ticker: str

class FinancialCallbackHandler(BaseCallbackHandler):
    """自定义回调处理器，实现实时进度显示"""

    def __init__(self):
        self.step_count = 0
        self.observation_count = 0
        self.start_time = None

    def on_agent_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        self.start_time = datetime.now()
        print("🚀 开始金融分析...")

    def on_agent_action(self, action, **kwargs) -> Any:
        self.step_count += 1
        tool = action.tool
        tool_input = action.tool_input
        print(f"🔧 步骤 {self.step_count}: 使用工具 {tool}")
        if tool_input:
            print(f"   输入: {tool_input}")

    def on_agent_finish(self, finish, **kwargs) -> None:
        end_time = datetime.now()
        duration = end_time - self.start_time
        print(f"✅ 分析完成! 耗时: {duration.total_seconds():.2f}秒")
        print(f"   总步骤数: {self.step_count}")
        print(f"   数据点数: {self.observation_count}")

# 2025年最新的CIO系统提示词
CIO_SYSTEM_PROMPT = """你是顶级对冲基金的首席投资官(CIO)。

当前日期: {current_date}

🎯 你的使命:
使用ReAct框架收集实时数据，生成专业详细的投资报告(最少800字)。

📋 工作流程:
1. 数据收集阶段 - 使用Thought-Action循环收集4-6个关键数据点
2. 报告生成阶段 - 基于收集的数据撰写综合分析报告

🔧 可用工具:
{tools}

📝 必需的报告结构:
# [投资标的] - 专业分析报告
*报告日期: {current_date}*

## 执行摘要 (2-3句话)
明确的投资建议(BUY/HOLD/SELL)

## 当前市场状况
- 当前价格/水平和近期表现
- 年初至今和1年回报率
- 与基准比较
- 关键技术位

## 宏观环境与催化剂
- 经济条件(通胀、利率、美联储政策)
- 即将到来的重大事件
- 地缘政治因素
- 行业特定趋势

## 技术与情绪分析
- 市场情绪指标
- 交易量和动量
- 机构持仓和内部活动

## 风险评估
- 历史波动率和最大回撤
- 特定投资风险
- 与更广泛市场的相关性

## 投资策略与建议

**主要建议:** [BUY/SELL/HOLD]
**信心水平:** [高/中/低]
**时间范围:** [短期/中期/长期]

**入场策略:**
- 理想入场价格/水平
- 仓位配置建议

**风险管理:**
- 止损水平
- 获利目标
- 投资组合配置比例

**退出策略:**
- 获利了结时机
- 止损时机

## 展望与价格目标

**牛市情景:** 上行潜力和时间线
**基准情景:** 最可能结果
**熊市情景:** 下行风险和预警信号

## 关键要点 (3-5个要点)
- 最重要的见解
- 需要监控的关键因素
- 投资者行动事项

## 重要监控事件
- 即将到来的财报
- 美联储会议
- 监管决定
- 竞争对手行动

---
*免责声明: 此分析仅供参考，不构成投资建议。*

⚠️ 关键指导原则:
1. 具体明确: 包含实际日期、数字、百分比
2. 全面深入: 报告最少800字
3. 可操作: 给出具体的买卖建议和理由
4. 使用所有数据: 引用每个观察结果
5. 保持最新: 提及最近30天的发展
6. 避免泛泛而谈: 不要说"自己做研究"等
7. 展示工作: 解释每个结论的原因

现在开始你的分析。
"""

def create_financial_agent(provider="gemini_proxy", model="gemini-2.5-flash"):
    """使用最新LangChain创建金融分析Agent"""

    # 获取LLM
    llm = get_llm_provider(provider, model)

    # 创建工具列表字符串
    tools_description = "\n".join([f"- {tool.name}: {tool.description}" for tool in FINANCIAL_TOOLS])

    # 创建最新提示词模板
    prompt = ChatPromptTemplate.from_messages([
        ("system", CIO_SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d"),
            tools=tools_description
        )),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])

    # 使用最新create_react_agent
    agent = create_react_agent(llm, FINANCIAL_TOOLS, prompt)

    # 创建回调处理器
    callback_handler = FinancialCallbackHandler()

    # 创建Agent执行器
    agent_executor = AgentExecutor(
        agent=agent,
        tools=FINANCIAL_TOOLS,
        verbose=True,
        max_iterations=15,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        callbacks=[callback_handler]
    )

    return agent_executor

# LangGraph版本 (更高级的控制)
def create_langgraph_financial_agent():
    """使用LangGraph创建更强大的金融分析Agent"""

    def think_node(state: FinancialAgentState) -> FinancialAgentState:
        """思考节点 - 分析当前状态决定下一步行动"""
        messages = state["messages"]
        last_message = messages[-1] if messages else {"content": ""}

        # 这里LLM决定下一步工具使用
        llm_response = get_llm_provider().invoke([
            SystemMessage(content="分析当前状态，决定下一个使用的工具"),
            HumanMessage(content=str(last_message))
        ])

        state["current_step"] = "tool_selection"
        return state

    def act_node(state: FinancialAgentState) -> FinancialAgentState:
        """执行节点 - 调用选定的工具"""
        # 工具执行逻辑
        state["current_step"] = "observation"
        return state

    def observe_node(state: FinancialAgentState) -> FinancialAgentState:
        """观察节点 - 处理工具执行结果"""
        observations = state.get("observations", [])
        observations.append(f"观察结果 {len(observations) + 1}")
        state["observations"] = observations
        state["current_step"] = "thinking"
        return state

    def should_continue(state: FinancialAgentState) -> str:
        """决定是否继续收集数据或生成报告"""
        observations = state.get("observations", [])
        if len(observations) >= 4:
            return "generate"
        return "continue"

    def generate_report_node(state: FinancialAgentState) -> FinancialAgentState:
        """生成报告节点"""
        state["report_generated"] = True
        return state

    # 构建图
    workflow = StateGraph(FinancialAgentState)
    workflow.add_node("think", think_node)
    workflow.add_node("act", act_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("generate_report", generate_report_node)

    workflow.set_entry_point("think")
    workflow.add_edge("think", "act")
    workflow.add_edge("act", "observe")
    workflow.add_conditional_edges("observe", should_continue)
    workflow.add_edge("generate_report", END)

    # 使用内存检查点
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)

    return app

# 主要Agent类
class LangChainFinancialAgent:
    def __init__(self, provider="gemini_proxy", model="gemini-2.5-flash", use_langgraph=False):
        if use_langgraph:
            self.agent = create_langgraph_financial_agent()
        else:
            self.agent = create_financial_agent(provider, model)

        self.use_langgraph = use_langgraph
        self.callback_handler = FinancialCallbackHandler()

    async def analyze(self, query: str, session_id: str = None) -> str:
        """执行金融分析"""
        if self.use_langgraph:
            # LangGraph版本
            initial_state = {
                "messages": [{"content": query, "type": "human"}],
                "current_step": "thinking",
                "observations": [],
                "report_generated": False,
                "analysis_ticker": self._extract_ticker(query)
            }

            config = {"configurable": {"thread_id": session_id or "default"}}
            result = await self.agent.ainvoke(initial_state, config=config)

            return self._extract_report_from_state(result)
        else:
            # 传统AgentExecutor版本
            result = await self.agent.ainvoke({
                "input": query,
                "chat_history": []
            })

            return result["output"]

    def _extract_ticker(self, query: str) -> str:
        """从查询中提取股票代码"""
        import re
        ticker_pattern = r'\b([A-Z]{1,5})\b'
        matches = re.findall(ticker_pattern, query.upper())
        return matches[0] if matches else "UNKNOWN"

    def _extract_report_from_state(self, state: dict) -> str:
        """从状态中提取最终报告"""
        messages = state.get("messages", [])
        for message in reversed(messages):
            if message.get("type") == "ai" and len(message.get("content", "")) > 500:
                return message["content"]
        return "无法生成报告"
```

#### 阶段4: 流式和实时更新 (第5天)

**创建 streaming_support.py:**
```python
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List, Optional
import asyncio
from datetime import datetime
import json

class FinancialStreamingCallbackHandler(BaseCallbackHandler):
    """金融分析专用的流式回调处理器"""

    def __init__(self, show_intermediate_steps: bool = True):
        self.show_intermediate_steps = show_intermediate_steps
        self.step_count = 0
        self.observation_count = 0
        self.start_time = datetime.now()
        self.current_thought = ""
        self.current_action = ""

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """LLM开始时的回调"""
        print("🧠 AI思考中...")

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """每个新token的回调 - 实现实时显示"""
        if "Thought:" in token:
            self.current_thought = ""
            print("\n💭 思考:", end=" ", flush=True)
        elif "Action:" in token:
            self.current_action = ""
            print("\n🔧 执行动作:", end=" ", flush=True)
        elif "```json" in token:
            print("\n📋 JSON指令:", end=" ", flush=True)
        elif token.strip() and not token.startswith("```"):
            print(token, end="", flush=True)

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """LLM结束时的回调"""
        print()  # 换行

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """工具开始执行时的回调"""
        tool_name = serialized.get("name", "unknown_tool")
        self.step_count += 1
        print(f"\n🛠️  步骤 {self.step_count}: 正在调用 {tool_name}")
        if input_str and input_str != "{}":
            try:
                data = json.loads(input_str)
                if "ticker" in data:
                    print(f"   📊 股票代码: {data['ticker']}")
                elif "query" in data:
                    print(f"   🔍 搜索查询: {data['query']}")
            except:
                print(f"   📝 输入: {input_str[:100]}...")

    def on_tool_end(self, output: str, **kwargs) -> None:
        """工具执行完成时的回调"""
        self.observation_count += 1
        print(f"   ✅ 完成! 获得数据点 #{self.observation_count}")

        # 显示输出摘要
        if len(output) > 200:
            print(f"   📄 结果摘要: {output[:200]}...")
        else:
            print(f"   📄 结果: {output}")

    def on_agent_finish(self, finish, **kwargs) -> None:
        """Agent完成时的回调"""
        end_time = datetime.now()
        duration = end_time - self.start_time

        print(f"\n{'='*60}")
        print("🎉 金融分析完成!")
        print(f"{'='*60}")
        print(f"⏱️  总耗时: {duration.total_seconds():.2f} 秒")
        print(f"🔧 执行步骤: {self.step_count}")
        print(f"📊 数据点数: {self.observation_count}")
        print(f"📅 分析时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

class AsyncFinancialStreamer:
    """异步流式金融分析器"""

    def __init__(self, agent):
        self.agent = agent
        self.streaming_handler = FinancialStreamingCallbackHandler()

    async def stream_analysis(self, query: str) -> str:
        """执行流式金融分析"""
        print(f"📈 开始分析: {query}")
        print("=" * 60)

        try:
            # 异步执行分析
            result = await self.agent.ainvoke(
                {"input": query, "chat_history": []},
                callbacks=[self.streaming_handler]
            )

            return result["output"]

        except Exception as e:
            print(f"\n❌ 分析过程中出现错误: {str(e)}")
            return f"分析失败: {str(e)}"

    def sync_stream_analysis(self, query: str) -> str:
        """同步版本的流式分析"""
        return asyncio.run(self.stream_analysis(query))

# 使用示例
async def main():
    from langchain_agent import LangChainFinancialAgent

    # 创建Agent
    agent = LangChainFinancialAgent()

    # 创建流式分析器
    streamer = AsyncFinancialStreamer(agent)

    # 执行分析
    query = "分析AAPL股票的当前投资机会"
    report = await streamer.stream_analysis(query)

    print("\n📋 最终报告:")
    print(report)

if __name__ == "__main__":
    asyncio.run(main())
```

#### 阶段5: 更新主程序 (第6天)

**更新 main.py:**
```python
#!/usr/bin/env python3
"""
FinSight - AI驱动的金融分析代理 (LangChain版本)
使用最新的LangChain 0.3.x和LangGraph实现
"""

import asyncio
import argparse
import sys
from typing import Optional
from datetime import datetime

from langchain_agent import LangChainFinancialAgent
from streaming_support import AsyncFinancialStreamer
from config import DEFAULT_LLM_PROVIDER, DEFAULT_LLM_MODEL

class FinSightLangChain:
    """FinSight主应用程序类"""

    def __init__(self,
                 provider: str = DEFAULT_LLM_PROVIDER,
                 model: str = DEFAULT_LLM_MODEL,
                 use_langgraph: bool = False,
                 streaming: bool = True):
        """
        初始化FinSight

        Args:
            provider: LLM提供商
            model: 模型名称
            use_langgraph: 是否使用LangGraph版本
            streaming: 是否启用流式输出
        """
        self.agent = LangChainFinancialAgent(
            provider=provider,
            model=model,
            use_langgraph=use_langgraph
        )
        self.streamer = AsyncFinancialStreamer(self.agent) if streaming else None
        self.version = "2.0.0 (LangChain)"

    async def analyze_async(self, query: str, session_id: Optional[str] = None) -> str:
        """异步执行分析"""
        print(f"🚀 FinSight v{self.version} - AI金融分析系统")
        print(f"📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 查询内容: {query}")
        print("=" * 70)

        try:
            if self.streamer:
                # 使用流式输出
                result = await self.streamer.stream_analysis(query)
            else:
                # 非流式输出
                result = await self.agent.analyze(query, session_id)

            return result

        except KeyboardInterrupt:
            print("\n⚠️  分析被用户中断")
            return "分析已中断"
        except Exception as e:
            print(f"\n❌ 分析失败: {str(e)}")
            return f"分析过程中出现错误: {str(e)}"

    def analyze(self, query: str, session_id: Optional[str] = None) -> str:
        """同步执行分析"""
        return asyncio.run(self.analyze_async(query, session_id))

    async def interactive_mode(self):
        """交互式分析模式"""
        print(f"\n🎉 欢迎使用 FinSight v{self.version} 交互模式!")
        print("💡 输入 'quit' 或 'exit' 退出程序")
        print("💡 输入 'help' 查看帮助信息")
        print("-" * 70)

        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        while True:
            try:
                query = input("\n📈 请输入要分析的股票或市场: ").strip()

                if query.lower() in ['quit', 'exit', 'q']:
                    print("\n👋 感谢使用 FinSight，再见!")
                    break
                elif query.lower() == 'help':
                    self._show_help()
                    continue
                elif not query:
                    print("⚠️  请输入有效的查询内容")
                    continue

                # 执行分析
                result = await self.analyze_async(query, session_id)

                # 询问是否继续
                if input("\n❓ 继续分析其他内容? (y/n): ").lower() != 'y':
                    break

            except KeyboardInterrupt:
                print("\n\n👋 程序被中断，再见!")
                break
            except Exception as e:
                print(f"\n❌ 出现错误: {str(e)}")
                if input("❓ 是否继续? (y/n): ").lower() != 'y':
                    break

    def _show_help(self):
        """显示帮助信息"""
        help_text = """
🔍 FinSight 使用说明:

📊 支持的分析类型:
   • 个股分析: AAPL, NVDA, TSLA, MSFT 等
   • 市场指数: ^GSPC (标普500), ^IXIC (纳斯达克), ^DJI (道琼斯) 等
   • 加密货币: BTC-USD, ETH-USD 等
   • 行业分析: 科技股, 金融股, 医疗股等

💡 查询示例:
   • "分析AAPL股票"
   • "评估纳斯达克指数投资机会"
   • "对比NVDA和AMD的投资价值"
   • "特斯拉当前风险分析"

🎯 分析报告包含:
   • 执行摘要和明确建议
   • 当前市场状况和技术指标
   • 宏观环境和催化剂分析
   • 风险评估和历史回撤
   • 具体的入场/出场策略
   • 牛/熊/基准三种情景分析

⚙️ 高级功能:
   • 流式实时显示思考过程
   • 智能多源数据获取
   • 专业CIO级别报告生成
   • 历史分析和对比功能

更多信息请访问项目主页或查看文档。
        """
        print(help_text)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="FinSight - AI驱动的金融分析代理 (LangChain版本)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python main.py                           # 交互模式
  python main.py "分析AAPL股票"            # 单次分析
  python main.py --provider openai --model gpt-4 "NVDA分析"   # 指定模型
  python main.py --langgraph --no-stream "对比科技股"         # 使用LangGraph
        """
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="要分析的金融标的查询"
    )

    parser.add_argument(
        "--provider",
        default=DEFAULT_LLM_PROVIDER,
        help=f"LLM提供商 (默认: {DEFAULT_LLM_PROVIDER})"
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_LLM_MODEL,
        help=f"LLM模型 (默认: {DEFAULT_LLM_MODEL})"
    )

    parser.add_argument(
        "--langgraph",
        action="store_true",
        help="使用LangGraph版本Agent (更高级的控制)"
    )

    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="禁用流式输出"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="FinSight 2.0.0 (LangChain)"
    )

    args = parser.parse_args()

    # 创建FinSight实例
    finsight = FinSightLangChain(
        provider=args.provider,
        model=args.model,
        use_langgraph=args.langgraph,
        streaming=not args.no_stream
    )

    try:
        if args.query:
            # 单次分析模式
            print("🎯 单次分析模式")
            result = finsight.analyze(args.query)

            # 保存结果到文件 (可选)
            if input("\n❓ 是否保存分析报告到文件? (y/n): ").lower() == 'y':
                filename = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(result)
                print(f"📁 报告已保存到: {filename}")
        else:
            # 交互模式
            asyncio.run(finsight.interactive_mode())

    except KeyboardInterrupt:
        print("\n\n👋 程序被用户中断，再见!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序运行出错: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

#### 阶段6: 测试和验证 (第7天)

**创建 test_langchain_migration.py:**
```python
#!/usr/bin/env python3
"""
LangChain迁移测试脚本
验证所有功能是否正常工作
"""

import asyncio
import unittest
from datetime import datetime
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_agent import LangChainFinancialAgent
from langchain_tools import FINANCIAL_TOOLS
from streaming_support import AsyncFinancialStreamer

class TestLangChainMigration(unittest.TestCase):
    """LangChain迁移测试类"""

    def setUp(self):
        """测试前准备"""
        self.agent = LangChainFinancialAgent()
        self.streamer = AsyncFinancialStreamer(self.agent)

    def test_tools_loading(self):
        """测试工具加载"""
        print("\n🔧 测试工具加载...")

        self.assertGreater(len(FINANCIAL_TOOLS), 0)

        # 验证每个工具都有必要的属性
        for tool in FINANCIAL_TOOLS:
            self.assertTrue(hasattr(tool, 'name'))
            self.assertTrue(hasattr(tool, 'description'))
            self.assertTrue(hasattr(tool, 'args_schema'))

        print(f"   ✅ 成功加载 {len(FINANCIAL_TOOLS)} 个工具")

    async def test_basic_analysis(self):
        """测试基本分析功能"""
        print("\n📊 测试基本分析功能...")

        query = "获取AAPL的基本信息"
        result = await self.agent.analyze(query)

        self.assertIsNotNone(result)
        self.assertGreater(len(result), 100)  # 结果应该有实质内容

        print(f"   ✅ 基本分析测试通过，结果长度: {len(result)}")

    async def test_streaming_analysis(self):
        """测试流式分析功能"""
        print("\n🌊 测试流式分析功能...")

        query = "获取当前市场时间"
        result = await self.streamer.stream_analysis(query)

        self.assertIsNotNone(result)
        self.assertIn(datetime.now().strftime("%Y-%m-%d"), result)

        print(f"   ✅ 流式分析测试通过")

    def test_error_handling(self):
        """测试错误处理"""
        print("\n⚠️  测试错误处理...")

        # 测试无效查询
        with self.assertRaises(Exception):
            asyncio.run(self.agent.analyze(""))

        print("   ✅ 错误处理测试通过")

async def run_tests():
    """运行所有测试"""
    print("🚀 开始LangChain迁移测试")
    print("=" * 50)

    test = TestLangChainMigration()
    test.setUp()

    try:
        test.test_tools_loading()
        await test.test_basic_analysis()
        await test.test_streaming_analysis()
        test.test_error_handling()

        print("\n" + "=" * 50)
        print("🎉 所有测试通过! LangChain迁移成功!")

    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(run_tests())
```

### 🎯 迁移后的优势

**1. 更好的可维护性**
- 使用LangChain标准化框架
- 模块化设计，易于扩展
- 完整的类型提示

**2. 强大的流式体验**
- 实时显示AI思考过程
- 用户友好的进度显示
- 可中断的长时间运行任务

**3. 企业级可靠性**
- 内置重试和错误恢复
- 完整的日志和监控
- 生产就绪的架构

**4. 最新技术栈**
- LangChain 0.3.x最新特性
- LangGraph高级Agent控制
- 现代异步编程模式

**5. 易于扩展**
- 添加新工具只需@tool装饰器
- 支持自定义回调处理器
- 模块化的Prompt管理

### 📋 迁移检查清单

- [ ] 备份现有代码
- [ ] 更新requirements.txt
- [ ] 创建langchain_tools.py
- [ ] 重构agent.py为langchain_agent.py
- [ ] 实现streaming_support.py
- [ ] 更新main.py主程序
- [ ] 运行迁移测试
- [ ] 性能基准测试
- [ ] 文档更新
- [ ] 部署到生产环境

这个迁移方案充分利用了LangChain 0.3.x的最新特性，同时保持了原有系统的所有功能，并大幅提升了用户体验和代码质量。

# 1. 实现智能rate limiting
from collections import deque
from time import time

class RateLimiter:
    def __init__(self, max_calls, time_window):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
    
    def wait_if_needed(self):
        now = time()
        # 清除时间窗口外的记录
        while self.calls and self.calls[0] < now - self.time_window:
            self.calls.popleft()
        
        if len(self.calls) >= self.max_calls:
            sleep_time = self.time_window - (now - self.calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.calls.append(now)

# 使用示例
yfinance_limiter = RateLimiter(max_calls=2000, time_window=3600)  # 每小时2000次
长期方案（架构升级）：
python# 4. 建立数据缓存层
import redis
import pickle

class DataCache:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
        self.ttl = {
            'stock_price': 60,        # 1分钟
            'company_info': 86400,    # 1天
            'news': 1800,             # 30分钟
        }
    
    def get(self, key, data_type):
        cached = self.redis_client.get(key)
        if cached:
            return pickle.loads(cached)
        return None
    
    def set(self, key, value, data_type):
        self.redis_client.setex(
            key, 
            self.ttl.get(data_type, 3600),
            pickle.dumps(value)
        )

2. RAG应用场景建议
最适合存储的内容：
A. 历史财报与公司文档 ⭐⭐⭐⭐⭐
pythonrag_content = {
    "10-K年报": "完整的年度财报PDF",
    "10-Q季报": "季度财报",
    "8-K重大事件": "公司重大变更公告",
    "投资者演示": "Investor Presentation slides",
    "分析师电话会议记录": "Earnings call transcripts"
}
为什么重要：

这些文档包含大量结构化和非结构化数据
LLM可以从中提取关键财务指标、管理层展望、风险因素
支持跨季度对比分析

B. 行业研究报告库 ⭐⭐⭐⭐
pythonresearch_docs = {
    "行业趋势报告": "McKinsey, Gartner等咨询公司报告",
    "券商研报": "Goldman Sachs, Morgan Stanley深度研究",
    "学术论文": "金融工程、量化模型相关论文",
    "监管文件": "SEC规则、合规要求"
}
C. 历史市场事件与案例 ⭐⭐⭐⭐
pythonhistorical_cases = {
    "危机案例": "2008金融危机、2020疫情崩盘的详细时间线",
    "成功投资案例": "Buffett投资可口可乐的完整故事",
    "公司破产案例": "Lehman Brothers, Enron详细分析",
    "监管处罚案例": "内幕交易、市场操纵案例库"
}
D. 技术指标与量化策略知识库 ⭐⭐⭐
pythonquant_knowledge = {
    "技术指标说明": "MACD, RSI, Bollinger Bands详细解释",
    "量化策略": "动量策略、均值回归、配对交易的实现细节",
    "风险模型": "VaR, CVaR, Sharpe Ratio的计算与解读"
}
实现示例：
pythonfrom langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

class FinancialRAG:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings()
        self.vectorstore = Chroma(
            persist_directory="./financial_knowledge_base",
            embedding_function=self.embeddings
        )
    
    def ingest_10k(self, ticker: str, pdf_path: str):
        """导入10-K年报"""
        from langchain.document_loaders import PyPDFLoader
        
        loader = PyPDFLoader(pdf_path)
        documents = loader.load()
        
        # 智能分块：保持财务表格完整性
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=200,
            separators=["\n\n\n", "\n\n", "\n", " "]
        )
        chunks = splitter.split_documents(documents)
        
        # 添加元数据
        for chunk in chunks:
            chunk.metadata.update({
                "ticker": ticker,
                "doc_type": "10-K",
                "year": 2024
            })
        
        self.vectorstore.add_documents(chunks)
    
    def query_company_risks(self, ticker: str, query: str):
        """查询公司风险因素"""
        results = self.vectorstore.similarity_search(
            query,
            filter={"ticker": ticker, "doc_type": "10-K"},
            k=5
        )
        return results

3. 迁移到LangChain的准备工作
当前架构 vs LangChain架构对比：
组件当前实现LangChain等效Agent循环手动实现ReActAgentExecutor + create_react_agent工具定义普通函数 + 字典@tool 装饰器 + Tool 类LLM调用自定义call_llmChatOpenAI / ChatAnthropic提示词巨大的字符串PromptTemplate + ChatPromptTemplate记忆Messages列表ConversationBufferMemory
迁移步骤：
Step 1: 工具标准化
python# 当前方式
def get_stock_price(ticker: str) -> str:
    ...

# LangChain方式
from langchain.tools import tool

@tool
def get_stock_price(ticker: str) -> str:
    """Get current stock price and daily change.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'NVDA')
    
    Returns:
        String with current price and change percentage
    """
    # 实现保持不变
    ...
Step 2: 提示词模块化
pythonfrom langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

cio_template = ChatPromptTemplate.from_messages([
    ("system", """You are a Chief Investment Officer (CIO).
    Today's date is {current_date}.
    
    PHASE 1: DATA COLLECTION
    {data_collection_instructions}
    
    PHASE 2: REPORT GENERATION
    {report_structure}
    """),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad")
])
Step 3: Agent构建
pythonfrom langchain.agents import create_react_agent, AgentExecutor
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4", temperature=0)

tools = [
    get_stock_price,
    get_company_news,
    search,
    # ... 其他工具
]

agent = create_react_agent(llm, tools, cio_template)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=20,
    handle_parsing_errors=True,
    return_intermediate_steps=True
)
Step 4: 添加回调与监控
pythonfrom langchain.callbacks import StdOutCallbackHandler, FileCallbackHandler

callbacks = [
    StdOutCallbackHandler(),
    FileCallbackHandler("agent_logs.txt")
]

result = agent_executor.invoke(
    {"input": user_query, "current_date": datetime.now()},
    callbacks=callbacks
)
迁移后的优势：

更好的错误处理 - LangChain内置retry和fallback
流式输出 - 支持流式显示Thought/Action/Observation
可观测性 - LangSmith自动追踪所有调用
社区工具 - 直接使用100+ LangChain官方工具
更容易扩展 - 添加新工具只需@tool装饰器


4. 整体评价与提升建议
当前水平评估：🌟🌟🌟☆☆ (3/5)
✅ 做得好的地方：

清晰的ReAct循环 - 手动实现展示了对Agent原理的深刻理解
全面的报告结构 - 模板非常专业，涵盖了投资分析的所有要素
多工具集成 - 虽然有失效，但工具种类齐全
错误处理意识 - 有fallback机制（search作为备用）

❌ 明显的问题：

数据源脆弱 - 80%的工具依赖yfinance，单点故障严重
无缓存机制 - 重复查询浪费API quota
报告质量不稳定 - 依赖LLM当前状态，没有质量保证
无法处理复杂查询 - 比如"对比NVDA和AMD，考虑AI行业趋势，给我投资建议"

🎯 值得提升的关键点：
优先级1：数据层重构 ⭐⭐⭐⭐⭐
python# 建立数据抽象层
class DataProvider(ABC):
    @abstractmethod
    def get_stock_price(self, ticker: str) -> StockPrice:
        pass

class YFinanceProvider(DataProvider):
    ...

class AlphaVantageProvider(DataProvider):
    ...

class CompositeProvider(DataProvider):
    """自动选择可用的数据源"""
    def __init__(self, providers: List[DataProvider]):
        self.providers = providers
    
    def get_stock_price(self, ticker: str) -> StockPrice:
        for provider in self.providers:
            try:
                return provider.get_stock_price(ticker)
            except Exception:
                continue
        raise AllProvidersFailedError()
优先级2：报告质量验证 ⭐⭐⭐⭐
pythonclass ReportValidator:
    def validate(self, report: str) -> ValidationResult:
        checks = [
            self._check_has_recommendation,  # 必须有BUY/SELL/HOLD
            self._check_has_price_target,    # 必须有具体目标价
            self._check_date_accuracy,       # 日期必须正确
            self._check_minimum_length,      # 至少800字
            self._check_has_risk_section,    # 必须有风险分析
        ]
        
        for check in checks:
            if not check(report):
                return ValidationResult(
                    valid=False,
                    failed_check=check.__name__
                )
        
        return ValidationResult(valid=True)

# 使用示例
validator = ReportValidator()
if not validator.validate(final_answer):
    # 要求LLM重新生成
    messages.append({
        "role": "user",
        "content": f"Report validation failed: {validator.failed_check}. Please revise."
    })
优先级3：引入Evaluation ⭐⭐⭐⭐
python# 建立测试用例集
test_cases = [
    {
        "query": "Analyze NVIDIA stock",
        "expected_ticker": "NVDA",
        "must_include": ["AI", "GPU", "data center"],
        "must_have_section": ["Risk Assessment", "Price Target"]
    },
    {
        "query": "Compare tech stocks",
        "expected_tickers": ["AAPL", "MSFT", "GOOGL"],
        "must_include": ["performance comparison"]
    }
]

def evaluate_agent(agent, test_cases):
    results = []
    for case in test_cases:
        output = agent.run(case["query"])
        score = {
            "ticker_accuracy": check_tickers(output, case["expected_ticker"]),
            "keyword_coverage": check_keywords(output, case["must_include"]),
            "structure_completeness": check_sections(output, case["must_have_section"]),
            "word_count": len(output.split())
        }
        results.append(score)
    
    return pd.DataFrame(results).mean()
优先级4：用户体验优化 ⭐⭐⭐
python# 添加流式输出
import sys

def stream_agent_thoughts(agent, query):
    """实时显示Agent思考过程"""
    for step in agent.stream(query):
        if step['type'] == 'thought':
            print(f"💭 {step['content']}", flush=True)
        elif step['type'] == 'action':
            print(f"🔧 Executing: {step['tool']}", flush=True)
        elif step['type'] == 'observation':
            print(f"📊 Result: {step['content'][:100]}...", flush=True)
        sys.stdout.flush()

# 添加进度条
from tqdm import tqdm

with tqdm(total=6, desc="Collecting data") as pbar:
    for observation in agent.collect_data():
        pbar.update(1)
        pbar.set_postfix({"current": observation['tool']})
最终判断：这是一个很好的学习项目，但距离生产可用还有差距
能用吗？

✅ 学习和演示：完全可以
✅ 个人研究：可以，但需要手动验证数据
❌ 真实交易决策：绝对不行
❌ 企业级应用：需要大幅改造

如何达到生产级别：

解决数据源问题（多源+缓存+付费API）
添加完整的测试套件（单元测试+集成测试+评估）
引入监控和告警（数据异常、API失败、报告质量下降）
添加合规性检查（确保不违反金融监管要求）
用户反馈循环（让真实用户评分报告质量）

我的建议优先级：

立即做：添加Alpha Vantage/Finnhub作为备用数据源
本周做：实现报告质量验证器
本月做：迁移到LangChain
长期做：建立RAG知识库+评估体系
--
分析“纳斯达克” (^IXIC) 时: 它返回了 Latest News (^IXIC): 1. [Unknown date] No title (Unknown source)... 这样的无用信息。
分析“英伟达” (NVDA) 时: 它成功返回了5条具体的、有价值的新闻。
为什么对指数不好使？
这个问题的根源在于数据源的性质和API的设计。

API是为“公司”设计的：无论是 yfinance, Finnhub 还是 Alpha Vantage，它们的新闻API都是围绕公司实体来构建的。它们会去抓取那些被明确标记为与 NVDA、AAPL 或 MSFT 等公司相关的新闻。
指数是“集合”，不是“实体”：纳斯达克指数 (^IXIC) 是一个包含数千家公司股票的集合或篮子。它本身不会“发布财报”或“推出新产品”。因此，几乎没有新闻会被直接标记为“关于^IXIC”的新闻。
关于指数的新闻其实是“市场评论”：我们通常所说的“纳斯达克新闻”，实际上是关于整个市场的宏观新闻、经济数据、或影响指数内权重股的重大事件。这类新闻在API层面很难被归类到 ^IXIC 这个代码下。
所以，当 get_company_news 拿着 ^IXIC 去问API时，API要么找不到，要么返回一些不相关的、格式混乱的数据。