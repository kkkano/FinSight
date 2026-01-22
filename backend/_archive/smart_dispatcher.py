# -*- coding: utf-8 -*-
"""
SmartDispatcher - 智能调度器
让 LLM 自主选择使用什么工具/Agent，而不是写死规则
"""

from typing import Dict, Any, Optional, List
import json


# 告诉 LLM 我们有什么能力
CAPABILITIES_PROMPT = """你是 FinSight 金融助手的智能调度器。根据用户问题，选择最合适的工具组合。

## 可用工具

### 数据获取工具 (tools_module)
| 工具 | 函数名 | 用途 |
|------|--------|------|
| 股票价格 | get_stock_price(ticker) | 获取实时股价、涨跌幅 |
| 公司信息 | get_company_info(ticker) | 获取公司简介、行业、市值 |
| 公司新闻 | get_company_news(ticker) | 获取最近新闻标题 |
| 市场情绪 | get_market_sentiment() | 获取恐惧贪婪指数 |
| 经济日历 | get_economic_events() | 获取近期宏观事件(CPI/FOMC等) |
| 新闻情绪 | get_news_sentiment(ticker) | 获取新闻情绪分析 |
| 财务报表 | get_financial_statements(ticker) | 获取财报数据(营收/利润/EPS) |
| 历史数据 | get_stock_historical_data(ticker) | 获取K线历史数据 |
| 表现对比 | get_performance_comparison(tickers) | 对比多个标的表现 |
| 回撤分析 | analyze_historical_drawdowns(ticker) | 分析历史最大回撤 |
| 通用搜索 | search(query) | 搜索任何金融相关信息 |

### 智能 Agent (带反思循环，更深入)
| Agent | 用途 | 耗时 |
|-------|------|------|
| NewsAgent | 深度新闻分析，会自动补充搜索 | 10-20秒 |
| PriceAgent | 多源价格获取，带缓存和熔断 | 3-5秒 |
| DeepSearchAgent | 深度研究，抓取长文分析 | 30-60秒 |
| MacroAgent | 宏观经济分析(FRED数据) | 10-15秒 |
| TechnicalAgent | 技术指标分析 | 5-10秒 |
| FundamentalAgent | 基本面分析 | 10-15秒 |

### 综合能力
| 能力 | 用途 | 耗时 |
|------|------|------|
| Supervisor | 并行调用多个Agent + Forum综合 | 30-60秒 |
| LLM直接回答 | 简单问题直接回答，不调用工具 | 1-2秒 |

## 选择原则

1. **简单问题用简单工具**：问价格就用 get_stock_price，不要用 Supervisor
2. **复杂问题才用 Agent**：需要深度分析时才用 Agent 或 Supervisor
3. **可以组合多个工具**：比如同时获取价格+新闻+情绪
4. **没有 ticker 时**：用 search 或直接 LLM 回答
5. **非金融问题**：直接 LLM 回答或礼貌拒绝

## 输出格式

请返回 JSON 格式：
```json
{
  "tools": ["get_stock_price", "get_company_news"],  // 要调用的工具列表
  "agents": [],  // 要调用的 Agent 列表
  "use_supervisor": false,  // 是否使用 Supervisor 多 Agent 协作
  "use_llm_direct": false,  // 是否直接用 LLM 回答（不调用任何工具）
  "tickers": ["AAPL"],  // 识别到的股票代码
  "reasoning": "用户只是问价格和新闻，用简单工具即可"  // 选择理由
}
```
"""


class SmartDispatcher:
    """
    智能调度器 - 让 LLM 自主选择工具/Agent
    """

    def __init__(self, llm, tools_module=None, agents: Dict = None, supervisor=None):
        """
        Args:
            llm: LLM 实例
            tools_module: 工具模块 (backend.tools)
            agents: Agent 字典 {"news": NewsAgent, "price": PriceAgent, ...}
            supervisor: AgentSupervisor 实例
        """
        self.llm = llm
        self.tools_module = tools_module
        self.agents = agents or {}
        self.supervisor = supervisor

    async def dispatch(self, query: str, context: str = "") -> Dict[str, Any]:
        """
        智能调度：让 LLM 决定用什么工具/Agent

        Args:
            query: 用户查询
            context: 对话上下文

        Returns:
            执行结果
        """
        # 1. 让 LLM 决定用什么
        plan = await self._plan(query, context)
        print(f"[SmartDispatcher] 计划: {plan}")

        # 2. 执行计划
        result = await self._execute(plan, query)

        # 3. 让 LLM 整合结果生成回复
        response = await self._synthesize(query, result, plan)

        return {
            "success": True,
            "response": response,
            "plan": plan,
            "raw_data": result,
        }

    async def _plan(self, query: str, context: str = "") -> Dict[str, Any]:
        """让 LLM 制定执行计划"""
        from langchain_core.messages import HumanMessage

        prompt = f"""{CAPABILITIES_PROMPT}

用户问题: {query}
对话上下文: {context or '无'}

请分析用户问题，选择最合适的工具组合，返回 JSON："""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            # 提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            plan = json.loads(content)
            return plan

        except Exception as e:
            print(f"[SmartDispatcher] 计划解析失败: {e}")
            # 回退：简单搜索
            return {
                "tools": ["search"],
                "agents": [],
                "use_supervisor": False,
                "use_llm_direct": False,
                "tickers": [],
                "reasoning": f"计划解析失败，使用搜索兜底: {e}"
            }

    async def _execute(self, plan: Dict[str, Any], query: str) -> Dict[str, Any]:
        """执行计划，调用工具/Agent"""
        import asyncio
        results = {}
        tickers = plan.get("tickers", [])
        ticker = tickers[0] if tickers else None

        # 1. 如果使用 Supervisor
        if plan.get("use_supervisor") and self.supervisor and ticker:
            try:
                sup_result = await self.supervisor.analyze(query, ticker, None)
                results["supervisor"] = sup_result
                return results
            except Exception as e:
                print(f"[SmartDispatcher] Supervisor 失败: {e}")

        # 2. 调用 Agent
        for agent_name in plan.get("agents", []):
            agent = self.agents.get(agent_name.lower().replace("agent", ""))
            if agent and ticker:
                try:
                    output = await agent.research(query, ticker)
                    results[agent_name] = output.summary if output else None
                except Exception as e:
                    print(f"[SmartDispatcher] Agent {agent_name} 失败: {e}")

        # 3. 调用工具
        for tool_name in plan.get("tools", []):
            if not self.tools_module:
                continue
            func = getattr(self.tools_module, tool_name, None)
            if not func:
                continue
            try:
                # 根据工具类型传参
                if tool_name in ["get_stock_price", "get_company_info", "get_company_news",
                                 "get_financial_statements", "get_stock_historical_data",
                                 "analyze_historical_drawdowns", "get_news_sentiment"]:
                    if ticker:
                        results[tool_name] = func(ticker)
                elif tool_name == "get_performance_comparison":
                    if len(tickers) >= 2:
                        results[tool_name] = func(tickers)
                elif tool_name == "search":
                    results[tool_name] = func(query)
                else:
                    # 无参数工具
                    results[tool_name] = func()
            except Exception as e:
                print(f"[SmartDispatcher] 工具 {tool_name} 失败: {e}")
                results[tool_name] = f"Error: {e}"

        return results

    async def _synthesize(self, query: str, data: Dict[str, Any], plan: Dict[str, Any]) -> str:
        """让 LLM 整合数据生成自然回复"""
        from langchain_core.messages import HumanMessage

        # 如果是直接 LLM 回答
        if plan.get("use_llm_direct"):
            prompt = f"用户问题: {query}\n请直接回答，简洁专业。"
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content

        # 整合数据
        data_str = "\n".join([f"【{k}】\n{v}" for k, v in data.items() if v])

        prompt = f"""用户问题: {query}

获取到的数据:
{data_str}

请根据数据回答用户问题：
1. 直接回答，2-4句话
2. 包含关键数字
3. 语气专业友好
4. 不要说"根据数据显示"等废话"""

        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content


# 同步包装器（兼容现有代码）
def create_smart_dispatcher(llm, tools_module=None, agents=None, supervisor=None):
    """创建智能调度器"""
    return SmartDispatcher(llm, tools_module, agents, supervisor)


async def stream_smart_dispatch(dispatcher: SmartDispatcher, query: str, context: str = ""):
    """
    流式智能调度 - 逐步返回执行过程和结果

    Yields:
        SSE 格式的事件流
    """
    import json

    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    # 1. 开始规划
    yield sse_event("planning", {"message": "正在分析问题，制定执行计划..."})

    try:
        plan = await dispatcher._plan(query, context)
        yield sse_event("plan", {
            "tools": plan.get("tools", []),
            "agents": plan.get("agents", []),
            "tickers": plan.get("tickers", []),
            "reasoning": plan.get("reasoning", "")
        })
    except Exception as e:
        yield sse_event("error", {"message": f"规划失败: {e}"})
        return

    # 2. 执行工具/Agent
    yield sse_event("executing", {"message": "正在执行计划..."})

    try:
        results = await dispatcher._execute(plan, query)
        for tool_name, result in results.items():
            yield sse_event("tool_result", {
                "tool": tool_name,
                "success": result is not None and "Error" not in str(result),
                "preview": str(result)[:200] if result else None
            })
    except Exception as e:
        yield sse_event("error", {"message": f"执行失败: {e}"})
        return

    # 3. 生成回复（流式）
    yield sse_event("synthesizing", {"message": "正在生成回复..."})

    try:
        response = await dispatcher._synthesize(query, results, plan)

        # 模拟流式输出（按句子分割）
        sentences = response.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
        for sentence in sentences:
            if sentence.strip():
                yield sse_event("token", {"content": sentence})

        yield sse_event("done", {
            "response": response,
            "plan": plan
        })
    except Exception as e:
        yield sse_event("error", {"message": f"生成回复失败: {e}"})
