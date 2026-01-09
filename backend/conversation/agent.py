# -*- coding: utf-8 -*-
"""
ConversationAgent - 对话式 Agent 统一入口
整合 Router、Context、Handlers 提供统一的对话接口
"""

import sys
import os
import asyncio
from typing import Dict, Any, Optional, Generator, List
from datetime import datetime

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.conversation.context import ContextManager
from backend.conversation.router import ConversationRouter, Intent
from backend.handlers.chat_handler import ChatHandler
from backend.handlers.report_handler import ReportHandler
from backend.handlers.followup_handler import FollowupHandler
from backend.orchestration.supervisor import AgentSupervisor


class ConversationAgent:
    """
    对话式股票分析 Agent

    统一入口，整合：
    - ConversationRouter: 意图识别
    - ContextManager: 上下文管理
    - ChatHandler: 快速对话
    - ReportHandler: 深度报告
    - FollowupHandler: 追问处理
    - AgentSupervisor: 多 Agent 调度 (Phase 1 新增)

    使用方式:
        agent = ConversationAgent()
        response = agent.chat("分析 AAPL")
    """

    def __init__(
        self,
        llm=None,
        orchestrator=None,
        report_agent=None,
        supervisor=None,
        max_context_turns: int = 10
    ):
        """
        初始化对话 Agent

        Args:
            llm: LLM 实例（用于增强响应）
            orchestrator: ToolOrchestrator 实例
            report_agent: 现有的报告生成 Agent（langchain_agent）
            supervisor: AgentSupervisor 实例
            max_context_turns: 最大上下文轮数
        """
        self.llm = llm
        self.orchestrator = orchestrator
        self.report_agent = report_agent
        self.supervisor = supervisor

        # 初始化核心组件
        self.context = ContextManager(max_turns=max_context_turns)
        self.router = ConversationRouter(llm=llm)

        # 初始化处理器
        self.chat_handler = ChatHandler(llm=llm, orchestrator=orchestrator)
        self.report_handler = ReportHandler(
            agent=report_agent,
            orchestrator=orchestrator,
            llm=llm
        )
        self.followup_handler = FollowupHandler(llm=llm, orchestrator=orchestrator)

        # 注册处理器到路由器
        self._register_handlers()

        # 统计信息
        self.stats = {
            'total_queries': 0,
            'intents': {
                'chat': 0,
                'report': 0,
                'alert': 0,
                'followup': 0,
                'clarify': 0,
                'greeting': 0
            },
            'errors': 0,
            'session_start': datetime.now(),
        }

    def _register_handlers(self):
        """注册意图处理器"""
        self.router.register_handler(Intent.CHAT, self._handle_chat)
        self.router.register_handler(Intent.REPORT, self._handle_report)
        self.router.register_handler(Intent.ALERT, self._handle_alert)
        self.router.register_handler(Intent.FOLLOWUP, self._handle_followup)
        self.router.register_handler(Intent.CLARIFY, self._handle_clarify)
        self.router.register_handler(Intent.GREETING, self._handle_greeting)

    def chat(self, query: str, capture_thinking: bool = False) -> Dict[str, Any]:
        """
        处理用户查询（主入口）

        Args:
            query: 用户输入
            capture_thinking: 是否捕获思考过程

        Returns:
            包含响应和元数据的字典
        """
        self.stats['total_queries'] += 1
        start_time = datetime.now()
        thinking_steps = [] if capture_thinking else None

        try:
            # 1. 解析指代（如果有上下文）
            if capture_thinking:
                thinking_steps.append({
                    "stage": "reference_resolution",
                    "message": "正在解析上下文引用...",
                    "timestamp": datetime.now().isoformat()
                })

            resolved_query = self.context.resolve_reference(query)

            # 2. 路由到对应处理器
            if capture_thinking:
                thinking_steps.append({
                    "stage": "intent_classification",
                    "message": "正在识别查询意图...",
                    "timestamp": datetime.now().isoformat()
                })

            intent, metadata, handler = self.router.route(resolved_query, self.context)

            if capture_thinking:
                thinking_steps.append({
                    "stage": "intent_classification",
                    "result": {
                        "intent": intent.value,
                        "tickers": metadata.get('tickers', []),
                        "company_names": metadata.get('company_names', [])
                    },
                    "timestamp": datetime.now().isoformat()
                })

            # 3. 更新统计
            self.stats['intents'][intent.value] = self.stats['intents'].get(intent.value, 0) + 1

            # 4. 数据收集阶段（如果有股票代码）
            if capture_thinking and metadata.get('tickers'):
                ticker = metadata['tickers'][0]
                thinking_steps.append({
                    "stage": "data_collection",
                    "message": f"正在获取 {ticker} 的数据...",
                    "timestamp": datetime.now().isoformat()
                })

            # 5. 调用处理器
            if capture_thinking:
                thinking_steps.append({
                    "stage": "processing",
                    "message": f"正在生成{intent.value}响应...",
                    "timestamp": datetime.now().isoformat()
                })

            if handler:
                result = handler(resolved_query, metadata)
            else:
                result = self._default_handler(resolved_query, metadata)

            if capture_thinking:
                thinking_steps.append({
                    "stage": "complete",
                    "message": "处理完成",
                    "timestamp": datetime.now().isoformat()
                })

            # 6. 更新上下文
            self.context.add_turn(
                query=query,
                intent=intent.value,
                response=result.get('response', ''),
                metadata=metadata
            )

            # 7. 自动添加图表标记（根据上下文和查询）
            # 只有 CHAT/REPORT 意图才尝试生成图表，闲聊不生成
            if intent in [Intent.CHAT, Intent.REPORT, Intent.FOLLOWUP]:
                result = self._add_chart_marker(result, query, metadata, resolved_query)

            # 8. 添加元信息
            result['intent'] = intent.value
            result['metadata'] = metadata
            result['response_time_ms'] = (datetime.now() - start_time).total_seconds() * 1000
            result['thinking_elapsed_seconds'] = round((datetime.now() - start_time).total_seconds(), 2)
            result['current_focus'] = self.context.current_focus

            if capture_thinking and thinking_steps:
                result['thinking'] = thinking_steps

            return result

        except Exception as e:
            self.stats['errors'] += 1
            import traceback
            traceback.print_exc()
            error_result = {
                'success': False,
                'response': f"处理查询时出错: {str(e)}",
                'error': str(e),
                'response_time_ms': (datetime.now() - start_time).total_seconds() * 1000,
                'thinking_elapsed_seconds': round((datetime.now() - start_time).total_seconds(), 2),
            }
            if capture_thinking and thinking_steps:
                error_result['thinking'] = thinking_steps
            return error_result


    async def chat_async(self, query: str, capture_thinking: bool = False) -> Dict[str, Any]:
        """
        Async version of chat() that can await Supervisor paths.
        """
        self.stats['total_queries'] += 1
        start_time = datetime.now()
        thinking_steps = [] if capture_thinking else None

        try:
            if capture_thinking:
                thinking_steps.append({
                    "stage": "reference_resolution",
                    "message": "正在解析上下文引用...",
                    "timestamp": datetime.now().isoformat()
                })

            resolved_query = self.context.resolve_reference(query)

            if capture_thinking:
                thinking_steps.append({
                    "stage": "intent_classification",
                    "message": "正在识别查询意图...",
                    "timestamp": datetime.now().isoformat()
                })

            intent, metadata, handler = self.router.route(resolved_query, self.context)

            if capture_thinking:
                thinking_steps.append({
                    "stage": "intent_classification",
                    "result": {
                        "intent": intent.value,
                        "tickers": metadata.get('tickers', []),
                        "company_names": metadata.get('company_names', [])
                    },
                    "timestamp": datetime.now().isoformat()
                })

            self.stats['intents'][intent.value] = self.stats['intents'].get(intent.value, 0) + 1

            if capture_thinking and metadata.get('tickers'):
                ticker = metadata['tickers'][0]
                thinking_steps.append({
                    "stage": "data_collection",
                    "message": f"正在获取 {ticker} 的数据...",
                    "timestamp": datetime.now().isoformat()
                })

            if capture_thinking:
                thinking_steps.append({
                    "stage": "processing",
                    "message": f"正在生成{intent.value}响应...",
                    "timestamp": datetime.now().isoformat()
                })

            if intent == Intent.REPORT and self.supervisor and metadata.get('tickers'):
                result = await self._handle_report_async(resolved_query, metadata)
            elif handler:
                result = await asyncio.to_thread(handler, resolved_query, metadata)
            else:
                result = await asyncio.to_thread(self._default_handler, resolved_query, metadata)

            if capture_thinking:
                thinking_steps.append({
                    "stage": "complete",
                    "message": "处理完成",
                    "timestamp": datetime.now().isoformat()
                })

            self.context.add_turn(
                query=query,
                intent=intent.value,
                response=result.get('response', ''),
                metadata=metadata
            )

            if intent in [Intent.CHAT, Intent.REPORT, Intent.FOLLOWUP]:
                result = self._add_chart_marker(result, query, metadata, resolved_query)

            result['intent'] = intent.value
            result['metadata'] = metadata
            result['response_time_ms'] = (datetime.now() - start_time).total_seconds() * 1000
            result['thinking_elapsed_seconds'] = round((datetime.now() - start_time).total_seconds(), 2)
            result['current_focus'] = self.context.current_focus

            if capture_thinking and thinking_steps:
                result['thinking'] = thinking_steps

            return result

        except Exception as e:
            self.stats['errors'] += 1
            import traceback
            traceback.print_exc()
            error_result = {
                'success': False,
                'response': f"处理查询时出错: {str(e)}",
                'error': str(e),
                'response_time_ms': (datetime.now() - start_time).total_seconds() * 1000,
                'thinking_elapsed_seconds': round((datetime.now() - start_time).total_seconds(), 2),
            }
            if capture_thinking and thinking_steps:
                error_result['thinking'] = thinking_steps
            return error_result

    def _handle_chat(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理快速对话"""
        if self.llm:
            return self.chat_handler.handle_with_llm(query, metadata, self.context)
        return self.chat_handler.handle(query, metadata, self.context)


    async def _handle_report_async(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Async report path that can await AgentSupervisor."""
        use_supervisor = bool(
            self.supervisor
            and metadata.get('tickers')
            and (self.report_agent is None or os.getenv("SUPERVISOR_REPORT_FORCE", "false").lower() in ("true", "1", "yes", "on"))
        )
        if use_supervisor:
            ticker = metadata['tickers'][0]
            try:
                analysis_result = await self.supervisor.analyze(query, ticker, user_profile=None)
                forum_output = analysis_result.get("forum_output")

                report_ir = None
                if forum_output and hasattr(self.report_handler, "_convert_to_report_ir"):
                    report_ir = self.report_handler._convert_to_report_ir(ticker, query, forum_output)
                elif forum_output and hasattr(self.report_handler, "_generate_simple_report_ir"):
                    report_ir = self.report_handler._generate_simple_report_ir(ticker, forum_output.consensus)

                response_text = forum_output.consensus if forum_output else ""
                result = {
                    'success': True,
                    'response': response_text,
                    'data': analysis_result,
                    'method': 'supervisor',
                }
                if report_ir:
                    result['report'] = report_ir
                return result
            except Exception as e:
                print(f"[Agent] Supervisor async call failed: {e}")

        return await asyncio.to_thread(self.report_handler.handle, query, metadata, self.context)

    def _handle_report(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理报告请求 (优先使用 Supervisor)"""
        use_supervisor = bool(
            self.supervisor
            and metadata.get('tickers')
            and (self.report_agent is None or os.getenv("SUPERVISOR_REPORT_FORCE", "false").lower() in ("true", "1", "yes", "on"))
        )
        if use_supervisor:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                try:
                    return asyncio.run(self._handle_report_async(query, metadata))
                except Exception as e:
                    print(f"[Agent] Supervisor 调用失败: {e}")
            except Exception as e:
                print(f"[Agent] Supervisor 调用异常: {e}")

        result = self.report_handler.handle(query, metadata, self.context)
        print(f"[Agent._handle_report] report_handler 返回 - report 存在: {'report' in result}, 字段: {list(result.keys())}")
        return result

    def _handle_alert(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理监控请求（待实现）"""
        tickers = metadata.get('tickers', [])
        ticker = tickers[0] if tickers else None
        if not ticker and self.context.current_focus:
            ticker = self.context.current_focus

        return {
            'success': True,
            'response': f"""📊 监控功能说明

您想监控 {ticker or '某支股票'} 的价格变动。

目前监控功能正在开发中，即将支持：
1. 价格突破提醒
2. 涨跌幅提醒
3. 成交量异常提醒
4. 新闻动态提醒

请稍后再试，或先使用价格查询功能了解当前行情。""",
            'intent': 'alert',
            'feature_status': 'coming_soon',
        }

    def _handle_followup(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理追问"""
        return self.followup_handler.handle(query, metadata, self.context)

    def _handle_greeting(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理问候和日常闲聊 (不调用搜索)"""
        if any(kw in query.lower() for kw in ['自我介绍', '你是谁', 'introduce yourself', 'who are you', '你是做', '你是干']):
            response = """我是一个专业的**金融对话式分析 Agent**，名叫 FinSight AI。

我的主要工作是帮助您快速获取和分析全球股票、指数、ETF 等金融市场信息，包括：
1. **实时行情查询**：股价、涨跌幅、K 线图等。
2. **深度报告生成**：对特定股票进行基本面、财务、估值、风险分析。
3. **行业趋势洞察**：分析市场热点和行业动向。
4. **投资建议**：根据您的需求提供中肯的投资建议。

您有什么想了解的股票（例如：**AAPL**）或金融问题吗？"""
        else:
            response = "您好！我是 FinSight AI 金融助手。您今天想了解哪支股票的行情，或者需要生成哪家公司的分析报告吗？"

        return {
            'success': True,
            'response': response,
            'intent': 'greeting',
        }

    def _handle_clarify(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理需要澄清的查询"""
        clarify_reason = metadata.get("clarify_reason")
        if clarify_reason == "followup_without_context":
            response = """看起来你是在追问上一条内容，但我这边没有上下文。可以告诉我你具体想追问哪只股票/指数/行业或哪条新闻吗？

例如：
1. "AAPL 为什么今天下跌？"
2. "最近市场热点有哪些？"
3. "解释一下刚才的结论：XXX"
"""
            return {
                'success': True,
                'response': response,
                'intent': 'clarify',
                'needs_clarification': True,
            }

        return {
            'success': True,
            'response': """抱歉，我不太确定您想了解什么。

我是专注于**金融市场分析**的助手。对于非金融类问题（如编程代码、天气、八卦娱乐等），我可能无法提供准确帮助。

您可以尝试问我：
1. 股票行情：**"AAPL 现在多少钱？"**
2. 公司分析：**"分析一下特斯拉"**
3. 投资建议：**"现在买英伟达怎么样？"**

请提供具体的股票代码或公司名称，重新提问！""",
            'intent': 'clarify',
            'needs_clarification': True,
        }

    def _default_handler(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """默认处理器"""
        return self._handle_chat(query, metadata)

    def _add_chart_marker(
        self,
        result: Dict[str, Any],
        original_query: str,
        metadata: Dict[str, Any],
        resolved_query: str
    ) -> Dict[str, Any]:
        """
        根据上下文和查询自动添加图表标记

        图表标记格式: [CHART:TICKER:TYPE]
        """
        try:
            # 问候/澄清等非行情意图不自动加图表
            intent = result.get('intent') or metadata.get('intent')
            if intent in {'greeting', 'clarify', 'followup', 'alert'}:
                return result

            from backend.api.chart_detector import ChartTypeDetector

            # 仅使用显式解析到的 ticker，避免沿用旧的 current_focus 误加图表
            ticker = None
            if metadata.get('tickers'):
                ticker = metadata['tickers'][0]

            if not ticker:
                return result

            # 检测图表类型
            query_lower = resolved_query.lower()

            # 特殊处理：持仓情况 -> 饼图
            if any(kw in query_lower for kw in ['持仓', '成分', '组成', '占比', '分布', 'holdings', 'constituent', 'composition']):
                chart_type = 'pie'
            # 对比查询 -> 柱状图
            elif any(kw in query_lower for kw in ['对比', '比较', 'vs', '区别', 'compare', 'difference']):
                chart_type = 'bar'
            # 价格/走势查询 -> K线图或折线图
            elif any(kw in query_lower for kw in ['价格', '走势', '趋势', 'k线', '涨跌', '表现', 'price', 'trend', 'chart']):
                chart_type = 'candlestick' if 'k线' in query_lower or 'candlestick' in query_lower else 'line'
            # 使用 ChartTypeDetector 检测
            else:
                chart_detection = ChartTypeDetector.detect_chart_type(resolved_query, ticker)
                chart_type = chart_detection.get('chart_type', 'line')

            # 如果检测到需要图表，添加标记
            if chart_type and ChartTypeDetector.should_generate_chart(resolved_query):
                chart_marker = f"[CHART:{ticker}:{chart_type}]"
                # 在响应末尾添加图表标记（如果还没有）
                if chart_marker not in result.get('response', ''):
                    result['response'] = result.get('response', '') + f'''

{chart_marker}'''
                    print(f"[Agent] 自动添加图表标记: {chart_marker}")

        except Exception as e:
            print(f"[Agent] 添加图表标记失败: {e}")

        return result

    def get_context_summary(self) -> str:
        """获取当前上下文摘要"""
        return self.context.get_summary()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            'context_turns': len(self.context.history),
            'current_focus': self.context.current_focus,
            'session_duration_seconds': (datetime.now() - self.stats['session_start']).total_seconds(),
        }

    def reset(self) -> None:
        """重置对话状态"""
        self.context.clear()
        self.stats = {
            'total_queries': 0,
            'intents': {'chat': 0, 'report': 0, 'alert': 0, 'followup': 0, 'clarify': 0, 'greeting': 0},
            'errors': 0,
            'session_start': datetime.now(),
        }

    def set_focus(self, ticker: str, company_name: str = None) -> None:
        """手动设置当前焦点"""
        self.context.current_focus = ticker
        if company_name:
            self.context.current_focus_name = company_name

    def describe_report_agent(self) -> Dict[str, Any]:
        """
        诊断报告 Agent（LangGraph）状态，供前端流水线面板/健康检查使用。
        不触发外部 LLM 调用。
        """
        info: Dict[str, Any] = {"available": False}
        if not getattr(self, "report_agent", None):
            info["error"] = "report_agent_not_initialized"
            return info
        info["available"] = True
        # 优先使用 self_check，其次 get_agent_info
        if hasattr(self.report_agent, "self_check"):
            try:
                info["self_check"] = self.report_agent.self_check()
            except Exception as exc:  # pragma: no cover (诊断路径)
                info["self_check_error"] = str(exc)
        if hasattr(self.report_agent, "get_agent_info"):
            try:
                info["agent_info"] = self.report_agent.get_agent_info()
            except Exception as exc:  # pragma: no cover
                info["agent_info_error"] = str(exc)
        if hasattr(self.report_agent, "get_recent_trace"):
            try:
                info["recent_trace"] = self.report_agent.get_recent_trace(10)
            except Exception as exc:  # pragma: no cover
                info["recent_trace_error"] = str(exc)
        return info


# === 便捷函数 ===

def create_agent(
    use_llm: bool = False,
    use_orchestrator: bool = True,
    use_report_agent: bool = False
) -> ConversationAgent:
    """
    创建 ConversationAgent 实例

    Args:
        use_llm: 是否使用 LLM 增强
        use_orchestrator: 是否使用 ToolOrchestrator
        use_report_agent: 是否使用现有的 LangChain Agent

    Returns:
        ConversationAgent 实例
    """
    llm = None
    orchestrator = None
    report_agent = None
    supervisor = None

    # 初始化 LLM
    if use_llm:
        try:
            # 尝试从 backend.config 导入
            try:
                from backend.config import get_llm_config
            except ImportError:
                # 回退到根目录 config
                from config import get_llm_config

            llm_config = get_llm_config()

            # 优先尝试使用 langchain_openai
            try:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model=llm_config.get('model', 'gpt-3.5-turbo'),
                    temperature=llm_config.get('temperature', 0.3),
                    openai_api_key=llm_config.get('api_key'),
                    openai_api_base=llm_config.get('api_base'),
                )
                print("[ConversationAgent] LLM 初始化成功 (langchain_openai)")
            except ImportError:
                # 如果 langchain_openai 不可用，尝试使用 litellm 创建兼容的 ChatModel
                try:
                    import litellm
                    from langchain_core.language_models.chat_models import BaseChatModel
                    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
                    from langchain_core.outputs import ChatGeneration, ChatResult
                    from langchain_core.callbacks.manager import CallbackManagerForLLMRun

                    class LiteLLMChatModel(BaseChatModel):
                        """LiteLLM ChatModel 包装器，兼容 LangChain ChatModel 接口"""
                        api_key: str
                        api_base: Optional[str] = None
                        model: str = "gpt-3.5-turbo"
                        temperature: float = 0.3

                        @property
                        def _llm_type(self) -> str:
                            return "litellm"

                        def _generate(
                            self,
                            messages: List[BaseMessage],
                            stop: Optional[List[str]] = None,
                            run_manager: Optional[CallbackManagerForLLMRun] = None,
                            **kwargs: Any,
                        ) -> ChatResult:
                            # 转换 LangChain messages 为 litellm 格式
                            litellm_messages = []
                            for msg in messages:
                                if isinstance(msg, HumanMessage):
                                    litellm_messages.append({"role": "user", "content": msg.content})
                                elif isinstance(msg, AIMessage):
                                    litellm_messages.append({"role": "assistant", "content": msg.content})

                            response = litellm.completion(
                                model=f"openai/{self.model}",
                                messages=litellm_messages,
                                api_key=self.api_key,
                                api_base=self.api_base,
                                temperature=self.temperature,
                                **kwargs
                            )

                            content = response.choices[0].message.content
                            message = AIMessage(content=content)
                            generation = ChatGeneration(message=message)
                            return ChatResult(generations=[generation])

                        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
                            # 流式输出暂不支持
                            result = self._generate(messages, stop, run_manager, **kwargs)
                            yield result.generations[0].message

                    llm = LiteLLMChatModel(
                        api_key=llm_config.get('api_key'),
                        api_base=llm_config.get('api_base'),
                        model=llm_config.get('model', 'gpt-3.5-turbo'),
                        temperature=llm_config.get('temperature', 0.3),
                    )
                    print("[ConversationAgent] LLM 初始化成功 (litellm)")
                except (ImportError, Exception) as e:
                    print(f"[ConversationAgent] 警告: LLM 初始化失败 ({e})，LLM 功能将不可用")
                    llm = None

        except Exception as e:
            print(f"[ConversationAgent] 初始化 LLM 失败: {e}")
            import traceback
            traceback.print_exc()
            llm = None

    # 初始化 Orchestrator
    if use_orchestrator:
        try:
            from backend.orchestration.orchestrator import ToolOrchestrator
            from backend.orchestration.tools_bridge import register_all_financial_tools

            orchestrator = ToolOrchestrator()
            register_all_financial_tools(orchestrator)
        except Exception as e:
            print(f"[ConversationAgent] 初始化 Orchestrator 失败: {e}")

    # 初始化 Report Agent
    if use_report_agent:
        try:
            from backend.langchain_agent import create_financial_agent
            report_agent = create_financial_agent()
            print("[ConversationAgent] Report Agent 初始化成功")
        except Exception as e:
            print(f"[ConversationAgent] 初始化 Report Agent 失败: {e}")
            import traceback
            traceback.print_exc()

    # 初始化 Agent Supervisor (New in Phase 1)
    if llm and orchestrator:
        try:
            from backend.orchestration.supervisor import AgentSupervisor
            # 需要传入 cache 和 circuit_breaker
            supervisor = AgentSupervisor(
                llm=llm,
                tools_module=orchestrator.tools_module, # Bridge 注册后的 module
                cache=orchestrator.cache,
                circuit_breaker=orchestrator.circuit_breaker
            )
            print("[ConversationAgent] Agent Supervisor 初始化成功")
        except Exception as e:
            print(f"[ConversationAgent] 初始化 Supervisor 失败: {e}")

    return ConversationAgent(
        llm=llm,
        orchestrator=orchestrator,
        report_agent=report_agent,
        supervisor=supervisor
    )
