# -*- coding: utf-8 -*-
"""
ConversationAgent - 对话式 Agent 统一入口
整合 Router、Context、Handlers 提供统一的对话接口
"""

import logging
import sys
import os
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Generator, List
from datetime import datetime

logger = logging.getLogger(__name__)


# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.conversation.context import ContextManager
from backend.conversation.router import ConversationRouter, Intent
from backend.handlers.chat_handler import ChatHandler
from backend.handlers.followup_handler import FollowupHandler
from backend.orchestration.supervisor_agent import SupervisorAgent
from backend.orchestration.intent_classifier import IntentClassifier, AgentIntent


@dataclass
class AgentGateDecision:
    """Decision record for reliability-first agent gating."""
    need_agent: bool = False
    should_use_supervisor: bool = False
    used_supervisor: Optional[bool] = None
    agent_path: Optional[str] = None
    policy: str = "reliability_first"
    router_intent: Optional[str] = None
    hard_triggers: List[str] = field(default_factory=list)
    soft_triggers: List[str] = field(default_factory=list)
    exclusion_reason: Optional[str] = None
    classifier_intent: Optional[str] = None
    classifier_confidence: Optional[float] = None
    classifier_method: Optional[str] = None
    classifier_reasoning: Optional[str] = None
    evidence_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "policy": self.policy,
            "router_intent": self.router_intent,
            "need_agent": self.need_agent,
            "should_use_supervisor": self.should_use_supervisor,
            "used_agent": self.used_supervisor,
            "agent_path": self.agent_path,
            "decision": self.agent_path or ("supervisor" if self.used_supervisor else "chat_handler"),
            "hard_triggers": self.hard_triggers,
            "soft_triggers": self.soft_triggers,
            "exclusion_reason": self.exclusion_reason,
            "classifier_intent": self.classifier_intent,
            "classifier_confidence": self.classifier_confidence,
            "classifier_method": self.classifier_method,
            "classifier_reasoning": self.classifier_reasoning,
            "evidence_required": self.evidence_required,
        }
        return {k: v for k, v in payload.items() if v not in (None, [], {})}


class ConversationAgent:
    """
    对话式股票分析 Agent

    统一入口，整合：
    - ConversationRouter: 意图识别
    - ContextManager: 上下文管理
    - ChatHandler: 快速对话
    - ReportHandler: 深度报告
    - FollowupHandler: 追问处理
    - SupervisorAgent: 多 Agent 调度 (Phase 1 新增)

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
            supervisor: SupervisorAgent 实例
            max_context_turns: 最大上下文轮数
        """
        self.llm = llm
        self.orchestrator = orchestrator
        self.report_agent = report_agent
        self.supervisor = supervisor

        # P1: 初始化子 Agent 供 ChatHandler 使用
        self.news_agent = None
        self.price_agent = None
        self._init_sub_agents()

        # 初始化核心组件
        self.context = ContextManager(max_turns=max_context_turns)
        self.router = ConversationRouter(llm=llm)

        # 初始化处理器 - P1: 传递子 Agent
        self.chat_handler = ChatHandler(
            llm=llm,
            orchestrator=orchestrator,
            news_agent=self.news_agent,
            price_agent=self.price_agent
        )
        # NOTE: ReportHandler 已废弃，报告生成统一走 Supervisor → Forum 流程
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
                'economic_events': 0,
                'news_sentiment': 0,
                'followup': 0,
                'clarify': 0,
                'greeting': 0
            },
            'errors': 0,
            'session_start': datetime.now(),
        }
        self._agent_intent_classifier: Optional[IntentClassifier] = None

    def _init_sub_agents(self):
        """P1: 初始化子 Agent 供 ChatHandler 使用"""
        if not self.llm:
            logger.info("[ConversationAgent] Sub-agents skipped: LLM not available")
            return
        if not self.orchestrator:
            logger.info("[ConversationAgent] Sub-agents skipped: Orchestrator not available")
            return

        try:
            from backend.agents.news_agent import NewsAgent
            from backend.agents.price_agent import PriceAgent
            from backend.services.circuit_breaker import CircuitBreaker

            cache = getattr(self.orchestrator, 'cache', None)
            tools_module = getattr(self.orchestrator, 'tools_module', None)

            # 使用 is None 检查，避免空缓存被误判为 falsy
            if cache is None:
                logger.info("[ConversationAgent] Sub-agents skipped: cache not available")
                return
            if tools_module is None:
                logger.info("[ConversationAgent] Sub-agents skipped: tools_module not available")
                return

            cb = CircuitBreaker()
            try:
                self.news_agent = NewsAgent(self.llm, cache, tools_module, cb)
                logger.info("[ConversationAgent] NewsAgent initialized")
            except Exception as e:
                logger.info(f"[ConversationAgent] NewsAgent init failed: {e}")

            try:
                self.price_agent = PriceAgent(self.llm, cache, tools_module, cb)
                logger.info("[ConversationAgent] PriceAgent initialized")
            except Exception as e:
                logger.info(f"[ConversationAgent] PriceAgent init failed: {e}")

        except ImportError as e:
            logger.info(f"[ConversationAgent] Failed to import sub-agents: {e}")
        except Exception as e:
            logger.info(f"[ConversationAgent] Failed to init sub-agents: {e}")

    def _register_handlers(self):
        """注册意图处理器"""
        self.router.register_handler(Intent.CHAT, self._handle_chat)
        self.router.register_handler(Intent.REPORT, self._handle_report)
        self.router.register_handler(Intent.ALERT, self._handle_alert)
        self.router.register_handler(Intent.ECONOMIC_EVENTS, self._handle_economic_events)
        self.router.register_handler(Intent.NEWS_SENTIMENT, self._handle_news_sentiment)
        self.router.register_handler(Intent.FOLLOWUP, self._handle_followup)
        self.router.register_handler(Intent.CLARIFY, self._handle_clarify)
        self.router.register_handler(Intent.GREETING, self._handle_greeting)

    def _add_thinking_step(self, steps, stage: str, message: str) -> Dict[str, Any]:
        step = {
            "stage": stage,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        steps.append(step)
        return step

    @staticmethod
    def _trim_text(value: Optional[str], limit: int = 200) -> Optional[str]:
        if value is None:
            return None
        return value if len(value) <= limit else value[:limit] + "..."

    @staticmethod
    def _compact_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in payload.items() if value not in (None, [], {})}

    def _get_agent_intent_classifier(self) -> IntentClassifier:
        if self._agent_intent_classifier is None:
            self._agent_intent_classifier = IntentClassifier(self.llm)
        return self._agent_intent_classifier

    def _serialize_agent_outputs(self, agent_outputs: Any) -> Any:
        if not isinstance(agent_outputs, dict):
            return agent_outputs
        serialized = {}
        for name, output in agent_outputs.items():
            if isinstance(output, dict):
                serialized[name] = output
                continue
            serialized[name] = {
                "summary": getattr(output, "summary", ""),
                "confidence": getattr(output, "confidence", None),
                "data_sources": getattr(output, "data_sources", None),
                "evidence": getattr(output, "evidence", None),
                "trace": getattr(output, "trace", None),
            }
        return serialized

    def _evaluate_agent_gate(
        self,
        query: str,
        intent: Intent,
        metadata: Dict[str, Any],
    ) -> AgentGateDecision:
        decision = AgentGateDecision(router_intent=intent.value if intent else None)

        # Hard exclusions
        if intent in {Intent.GREETING, Intent.CLARIFY}:
            decision.exclusion_reason = f"router_{intent.value}"
            return decision
        if intent == Intent.ALERT:
            decision.exclusion_reason = "alert_flow"
            return decision

        if not self.supervisor:
            decision.exclusion_reason = "supervisor_unavailable"
            return decision

        query_lower = query.lower()
        tickers = metadata.get("tickers", []) if isinstance(metadata, dict) else []

        time_keywords = [
            "现在", "最新", "今天", "本周", "近期", "最近", "实时",
            "current", "latest", "today", "this week", "recent",
        ]
        decision_keywords = [
            "推荐", "买", "卖", "值不值得", "值得", "应该", "前景", "风险",
            "原因", "为什么", "逻辑", "预测", "建议", "怎么做", "买入", "卖出", "持有",
            "recommend", "should i", "worth", "risk", "why", "reason", "forecast",
        ]
        comparison_keywords = [
            "对比", "比较", "vs", "versus", "哪个好", "哪个更好", "选哪个",
            "difference", "compare",
        ]
        analysis_keywords = [
            "分析", "研报", "报告", "深度", "研究", "analysis", "report", "research",
        ]
        financial_keywords = [
            "财报", "营收", "利润", "现金流", "资产负债", "估值", "pe", "eps", "roe",
            "roa", "市盈率", "市净率", "基本面", "earnings", "revenue", "profit",
            "cash flow", "valuation",
        ]
        news_keywords = ["新闻", "快讯", "消息", "头条", "news", "headline", "热点", "公告", "事件"]
        sentiment_keywords = ["情绪", "恐惧", "贪婪", "舆情", "sentiment", "fear", "greed", "media sentiment"]
        macro_keywords = [
            "宏观", "cpi", "ppi", "gdp", "fomc", "利率", "非农", "就业", "通胀",
            "macro", "economic calendar", "economic events", "央行",
        ]

        has_financial_context = bool(tickers) or any(
            kw in query_lower for kw in (financial_keywords + news_keywords + sentiment_keywords + macro_keywords)
        )

        if any(kw in query_lower for kw in time_keywords):
            decision.hard_triggers.append("timeliness")
        if any(kw in query_lower for kw in decision_keywords):
            decision.hard_triggers.append("decision")
        if metadata.get("is_comparison") or any(kw in query_lower for kw in comparison_keywords):
            decision.hard_triggers.append("comparison")
        if any(kw in query_lower for kw in financial_keywords):
            decision.hard_triggers.append("fundamental")
        if any(kw in query_lower for kw in news_keywords):
            decision.hard_triggers.append("news")
        if any(kw in query_lower for kw in sentiment_keywords):
            decision.hard_triggers.append("sentiment")
        if any(kw in query_lower for kw in macro_keywords):
            decision.hard_triggers.append("macro")
        if has_financial_context and any(kw in query_lower for kw in analysis_keywords):
            decision.hard_triggers.append("analysis")

        classifier = self._get_agent_intent_classifier()
        classification = classifier.classify(query, tickers, context_summary=self.context.get_summary())
        decision.classifier_intent = classification.intent.value
        decision.classifier_confidence = classification.confidence
        decision.classifier_method = classification.method
        decision.classifier_reasoning = classification.reasoning

        if classification.confidence < 0.70:
            decision.soft_triggers.append("low_confidence")
        if len(tickers) >= 2 and "comparison" not in decision.hard_triggers:
            decision.soft_triggers.append("multi_ticker")
        if tickers and not decision.hard_triggers and classification.intent in {
            AgentIntent.SEARCH, AgentIntent.CLARIFY, AgentIntent.OFF_TOPIC
        }:
            decision.soft_triggers.append("ticker_unclear")
        if classification.intent in {
            AgentIntent.REPORT, AgentIntent.COMPARISON, AgentIntent.FUNDAMENTAL,
            AgentIntent.TECHNICAL, AgentIntent.MACRO, AgentIntent.NEWS, AgentIntent.SENTIMENT
        } and classification.confidence >= 0.70:
            decision.soft_triggers.append("classifier_requires_agent")

        decision.need_agent = bool(decision.hard_triggers or decision.soft_triggers)
        decision.evidence_required = decision.need_agent
        decision.should_use_supervisor = decision.need_agent

        return decision

    def evaluate_agent_gate(
        self,
        query: str,
        intent: Intent,
        metadata: Dict[str, Any],
    ) -> AgentGateDecision:
        """Public wrapper for agent gate evaluation."""
        return self._evaluate_agent_gate(query, intent, metadata)

    def _convert_supervisor_result(self, result: Any) -> Dict[str, Any]:
        classification = getattr(result, "classification", None)
        classification_payload = None
        if classification:
            classification_payload = {
                "intent": classification.intent.value,
                "confidence": classification.confidence,
                "method": classification.method,
                "reasoning": classification.reasoning,
                "scores": classification.scores,
                "tickers": classification.tickers,
            }
        data = {
            "agent_outputs": self._serialize_agent_outputs(getattr(result, "agent_outputs", None)),
            "classification": classification_payload,
            "errors": getattr(result, "errors", None),
            "budget": getattr(result, "budget", None),
        }
        response_text = str(result.response) if getattr(result, "response", None) is not None else ""
        return {
            "success": bool(getattr(result, "success", True)),
            "response": response_text,
            "data": self._compact_dict(data),
            "method": "supervisor",
            "agent_used": True,
            "agent_path": "supervisor",
            "agent_intent": getattr(result, "intent", None).value if getattr(result, "intent", None) else None,
        }

    async def _run_supervisor_process_async(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if not self.supervisor:
            return {
                "success": False,
                "response": "Supervisor 不可用，已回退到快速回答。",
                "intent": "chat",
                "agent_used": False,
                "agent_path": "chat_handler",
            }
        tickers = metadata.get("tickers", []) if isinstance(metadata, dict) else []
        result = await self.supervisor.process(
            query=query,
            tickers=tickers,
            context_summary=self.context.get_summary(),
            context_ticker=self.context.current_focus,
        )
        return self._convert_supervisor_result(result)

    def _run_supervisor_process(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if not self.supervisor:
            return {
                "success": False,
                "response": "Supervisor 不可用，已回退到快速回答。",
                "intent": "chat",
                "agent_used": False,
                "agent_path": "chat_handler",
            }
        tickers = metadata.get("tickers", []) if isinstance(metadata, dict) else []
        try:
            asyncio.get_running_loop()
            logger.info("[AgentGate] 已有事件循环，无法同步调用 Supervisor")
            return {
                "success": False,
                "response": "Supervisor 仅支持异步调用，请使用流式接口。",
                "intent": "chat",
                "agent_used": False,
                "agent_path": "chat_handler",
            }
        except RuntimeError:
            result = asyncio.run(self.supervisor.process(
                query=query,
                tickers=tickers,
                context_summary=self.context.get_summary(),
                context_ticker=self.context.current_focus,
            ))
            return self._convert_supervisor_result(result)

    def _build_collection_result(self, metadata: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        data = result.get("data") or {}
        payload = {
            "ticker": metadata.get("tickers", [None])[0] if metadata.get("tickers") else None,
            "data_origin": data.get("data_origin") or data.get("source"),
            "tried_sources": data.get("tried_sources"),
            "fallback_used": data.get("fallback_used"),
            "as_of": data.get("as_of"),
            "trace": data.get("trace"),
            "plan": data.get("plan"),
            "plan_trace": data.get("plan_trace"),
        }
        deep_search = data.get("deep_search") if isinstance(data, dict) else None
        if isinstance(deep_search, dict):
            evidence = deep_search.get("evidence") or []
            pdf_count = sum(
                1 for item in evidence
                if isinstance(item, dict) and item.get("meta", {}).get("is_pdf")
            )
            payload["deep_search"] = self._compact_dict({
                "summary": deep_search.get("summary"),
                "confidence": deep_search.get("confidence"),
                "data_sources": deep_search.get("data_sources"),
                "evidence_count": len(evidence),
                "pdf_count": pdf_count,
                "evidence": evidence,
                "trace": deep_search.get("trace"),
            })

        agent_outputs = data.get("agent_outputs") if isinstance(data, dict) else None
        if isinstance(agent_outputs, dict):
            agents = []
            for name, output in agent_outputs.items():
                try:
                    if isinstance(output, dict):
                        summary = output.get("summary", "")
                        confidence = output.get("confidence")
                        data_sources = output.get("data_sources", [])
                        evidence = output.get("evidence") or []
                        trace = output.get("trace", [])
                    else:
                        summary = getattr(output, "summary", "")
                        confidence = getattr(output, "confidence", None)
                        data_sources = getattr(output, "data_sources", [])
                        evidence = getattr(output, "evidence", []) or []
                        trace = getattr(output, "trace", [])
                    agents.append(self._compact_dict({
                        "agent": name,
                        "summary": summary,
                        "confidence": confidence,
                        "data_sources": data_sources,
                        "evidence_count": len(evidence),
                        "trace": trace,
                    }))
                except Exception:
                    continue
            if agents:
                payload["agents"] = agents
        return self._compact_dict(payload)

    def _build_processing_result(
        self,
        intent: Intent,
        handler: Optional[Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        data = result.get("data") or {}
        if handler:
            handler_name = handler.__name__
        else:
            handler_name = "supervisor" if result.get("agent_path") == "supervisor" else "default_handler"
        payload = {
            "intent": intent.value,
            "handler": handler_name,
            "method": result.get("method"),
            "success": result.get("success", True),
            "agent_used": result.get("agent_used"),
            "agent_path": result.get("agent_path"),
            "agent_intent": result.get("agent_intent"),
            "intent_detail": result.get("intent_detail"),
            "data_origin": data.get("data_origin") or data.get("source"),
            "tried_sources": data.get("tried_sources"),
            "fallback_used": data.get("fallback_used"),
            "response_preview": self._trim_text(result.get("response", "")),
            "note": result.get("thinking"),
            "report_present": bool(result.get("report")),
        }
        return self._compact_dict(payload)

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
        reference_step = None
        intent_step = None
        gate_step = None
        collection_step = None
        processing_step = None

        try:
            user_query = query
            preprocess = self.context.preprocess_query(query)
            prepared_query = preprocess.get("query", query)

            # 1. 解析指代（如果有上下文）
            if capture_thinking:
                reference_step = self._add_thinking_step(
                    thinking_steps,
                    "reference_resolution",
                    "正在解析上下文引用..."
                )

            resolved_query = self.context.resolve_reference(prepared_query)
            if capture_thinking and reference_step is not None:
                reference_step["result"] = self._compact_dict({
                    "original_query": user_query,
                    "preprocessed_query": prepared_query,
                    "resolved_query": resolved_query,
                    "selection_reason": preprocess.get("selection_reason"),
                    "selected_ticker": preprocess.get("selected_ticker"),
                    "market_hint": preprocess.get("market_hint"),
                    "current_focus": self.context.current_focus,
                    "context_summary": self._trim_text(self.context.get_summary(), 200),
                })

            # 2. 路由到对应处理器
            if capture_thinking:
                intent_step = self._add_thinking_step(
                    thinking_steps,
                    "intent_classification",
                    "正在识别查询意图..."
                )

            intent, metadata, handler = self.router.route(resolved_query, self.context)

            schema_action = metadata.get("schema_action")
            schema_tool_name = metadata.get("schema_tool_name")
            schema_args = metadata.get("schema_args") or {}
            schema_direct = bool(
                schema_action == "execute"
                and schema_tool_name
                and schema_tool_name != "analyze_stock"
            )

            if capture_thinking and intent_step is not None:
                intent_step["result"] = self._compact_dict({
                    "intent": intent.value,
                    "tickers": metadata.get('tickers', []),
                    "company_names": metadata.get('company_names', []),
                    "is_comparison": metadata.get('is_comparison'),
                    "schema_action": metadata.get('schema_action'),
                    "schema_tool_name": metadata.get('schema_tool_name'),
                })

            # 2.1 Agent gate (reliability-first)
            if capture_thinking:
                gate_step = self._add_thinking_step(
                    thinking_steps,
                    "agent_gate",
                    "评估是否需要调用多Agent..."
                )
            if schema_direct:
                gate_decision = AgentGateDecision(router_intent=intent.value if intent else None)
                gate_decision.policy = "schema_router"
                gate_decision.exclusion_reason = "schema_direct_tool"
                gate_decision.need_agent = False
                gate_decision.should_use_supervisor = False
                gate_decision.used_supervisor = False
                gate_decision.agent_path = "chat_handler"
                use_supervisor = False
            else:
                gate_decision = self._evaluate_agent_gate(resolved_query, intent, metadata)
                use_supervisor = bool(gate_decision.should_use_supervisor and intent != Intent.REPORT and self.supervisor)
                gate_decision.used_supervisor = bool(
                    use_supervisor or (intent == Intent.REPORT and self.supervisor)
                )
                gate_decision.agent_path = "supervisor" if gate_decision.used_supervisor else "chat_handler"
            metadata["agent_gate"] = gate_decision.to_dict()
            if capture_thinking and gate_step is not None:
                gate_step["result"] = self._compact_dict(gate_decision.to_dict())

            # 3. 更新统计
            self.stats['intents'][intent.value] = self.stats['intents'].get(intent.value, 0) + 1

            # 4. 数据收集阶段（如果有股票代码）
            if capture_thinking and metadata.get('tickers'):
                ticker = metadata['tickers'][0]
                collection_step = self._add_thinking_step(
                    thinking_steps,
                    "data_collection",
                    f"正在获取 {ticker} 的数据..."
                )

            # 5. 调用处理器
            if capture_thinking:
                processing_step = self._add_thinking_step(
                    thinking_steps,
                    "processing",
                    f"正在生成{intent.value}响应..."
                )

            handler_used = handler
            if schema_direct:
                result = self.chat_handler.handle_schema_tool(
                    schema_tool_name, schema_args, resolved_query, self.context
                )
                handler_used = self.chat_handler.handle_schema_tool
            elif intent == Intent.REPORT and self.supervisor:
                result = self._handle_report(resolved_query, metadata)
                handler_used = None
            elif use_supervisor:
                result = self._run_supervisor_process(resolved_query, metadata)
                handler_used = None
            elif handler:
                result = handler(resolved_query, metadata)
            else:
                result = self._default_handler(resolved_query, metadata)

            if isinstance(result, dict):
                result.setdefault("agent_used", bool(use_supervisor or (intent == Intent.REPORT and self.supervisor)))
                result.setdefault("agent_path", "supervisor" if result.get("agent_used") else "chat_handler")
                if result.get("agent_used") and not result.get("agent_intent"):
                    result["agent_intent"] = "report" if intent == Intent.REPORT else None
                result["agent_gate"] = metadata.get("agent_gate")

            if capture_thinking:
                if collection_step is not None:
                    collection_step["result"] = self._build_collection_result(metadata, result)
                if processing_step is not None:
                    processing_step["result"] = self._build_processing_result(intent, handler_used, result)
                complete_step = self._add_thinking_step(
                    thinking_steps,
                    "complete",
                    "处理完成"
                )
                complete_step["result"] = self._compact_dict({
                    "elapsed_seconds": round((datetime.now() - start_time).total_seconds(), 2),
                    "success": result.get("success", True),
                    "report_present": bool(result.get("report")),
                })

            # 6. 更新上下文
            self.context.add_turn(
                query=user_query,
                intent=intent.value,
                response=result.get('response', ''),
                metadata=metadata
            )

            # 7. 自动添加图表标记（根据上下文和查询）
            # 只有 CHAT/REPORT 意图才尝试生成图表，闲聊不生成
            if intent in [Intent.CHAT, Intent.REPORT, Intent.FOLLOWUP]:
                result = self._add_chart_marker(result, user_query, metadata, resolved_query)

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
            if capture_thinking and thinking_steps is not None:
                error_step = self._add_thinking_step(
                    thinking_steps,
                    "error",
                    "处理失败"
                )
                error_step["result"] = {"error": str(e)}
                error_result['thinking'] = thinking_steps
            return error_result


    async def chat_async(self, query: str, capture_thinking: bool = False) -> Dict[str, Any]:
        """
        Async version of chat() that can await Supervisor paths.
        """
        self.stats['total_queries'] += 1
        start_time = datetime.now()
        thinking_steps = [] if capture_thinking else None
        reference_step = None
        intent_step = None
        gate_step = None
        collection_step = None
        processing_step = None

        try:
            user_query = query
            preprocess = self.context.preprocess_query(query)
            prepared_query = preprocess.get("query", query)

            if capture_thinking:
                reference_step = self._add_thinking_step(
                    thinking_steps,
                    "reference_resolution",
                    "正在解析上下文引用..."
                )

            resolved_query = self.context.resolve_reference(prepared_query)
            if capture_thinking and reference_step is not None:
                reference_step["result"] = self._compact_dict({
                    "original_query": user_query,
                    "preprocessed_query": prepared_query,
                    "resolved_query": resolved_query,
                    "selection_reason": preprocess.get("selection_reason"),
                    "selected_ticker": preprocess.get("selected_ticker"),
                    "market_hint": preprocess.get("market_hint"),
                    "current_focus": self.context.current_focus,
                    "context_summary": self._trim_text(self.context.get_summary(), 200),
                })

            if capture_thinking:
                intent_step = self._add_thinking_step(
                    thinking_steps,
                    "intent_classification",
                    "正在识别查询意图..."
                )

            intent, metadata, handler = self.router.route(resolved_query, self.context)

            schema_action = metadata.get("schema_action")
            schema_tool_name = metadata.get("schema_tool_name")
            schema_args = metadata.get("schema_args") or {}
            schema_direct = bool(
                schema_action == "execute"
                and schema_tool_name
                and schema_tool_name != "analyze_stock"
            )

            if capture_thinking and intent_step is not None:
                intent_step["result"] = self._compact_dict({
                    "intent": intent.value,
                    "tickers": metadata.get('tickers', []),
                    "company_names": metadata.get('company_names', []),
                    "is_comparison": metadata.get('is_comparison'),
                    "schema_action": metadata.get('schema_action'),
                    "schema_tool_name": metadata.get('schema_tool_name'),
                })

            # Agent gate (reliability-first)
            if capture_thinking:
                gate_step = self._add_thinking_step(
                    thinking_steps,
                    "agent_gate",
                    "评估是否需要调用多Agent..."
                )
            if schema_direct:
                gate_decision = AgentGateDecision(router_intent=intent.value if intent else None)
                gate_decision.policy = "schema_router"
                gate_decision.exclusion_reason = "schema_direct_tool"
                gate_decision.need_agent = False
                gate_decision.should_use_supervisor = False
                gate_decision.used_supervisor = False
                gate_decision.agent_path = "chat_handler"
                use_supervisor = False
            else:
                gate_decision = self._evaluate_agent_gate(resolved_query, intent, metadata)
                use_supervisor = bool(gate_decision.should_use_supervisor and intent != Intent.REPORT and self.supervisor)
                gate_decision.used_supervisor = bool(
                    use_supervisor or (intent == Intent.REPORT and self.supervisor)
                )
                gate_decision.agent_path = "supervisor" if gate_decision.used_supervisor else "chat_handler"
            metadata["agent_gate"] = gate_decision.to_dict()
            if capture_thinking and gate_step is not None:
                gate_step["result"] = self._compact_dict(gate_decision.to_dict())

            self.stats['intents'][intent.value] = self.stats['intents'].get(intent.value, 0) + 1

            if capture_thinking and metadata.get('tickers'):
                ticker = metadata['tickers'][0]
                collection_step = self._add_thinking_step(
                    thinking_steps,
                    "data_collection",
                    f"正在获取 {ticker} 的数据..."
                )

            if capture_thinking:
                processing_step = self._add_thinking_step(
                    thinking_steps,
                    "processing",
                    f"正在生成{intent.value}响应..."
                )

            handler_used = handler
            if schema_direct:
                result = await asyncio.to_thread(
                    self.chat_handler.handle_schema_tool,
                    schema_tool_name,
                    schema_args,
                    resolved_query,
                    self.context,
                )
                handler_used = self.chat_handler.handle_schema_tool
            elif intent == Intent.REPORT and self.supervisor and metadata.get('tickers'):
                result = await self._handle_report_async(resolved_query, metadata)
                handler_used = None
            elif use_supervisor:
                result = await self._run_supervisor_process_async(resolved_query, metadata)
                handler_used = None
            elif handler:
                result = await asyncio.to_thread(handler, resolved_query, metadata)
            else:
                result = await asyncio.to_thread(self._default_handler, resolved_query, metadata)

            if isinstance(result, dict):
                result.setdefault("agent_used", bool(use_supervisor or (intent == Intent.REPORT and self.supervisor)))
                result.setdefault("agent_path", "supervisor" if result.get("agent_used") else "chat_handler")
                if result.get("agent_used") and not result.get("agent_intent"):
                    result["agent_intent"] = "report" if intent == Intent.REPORT else None
                result["agent_gate"] = metadata.get("agent_gate")

            if capture_thinking:
                if collection_step is not None:
                    collection_step["result"] = self._build_collection_result(metadata, result)
                if processing_step is not None:
                    processing_step["result"] = self._build_processing_result(intent, handler_used, result)
                complete_step = self._add_thinking_step(
                    thinking_steps,
                    "complete",
                    "处理完成"
                )
                complete_step["result"] = self._compact_dict({
                    "elapsed_seconds": round((datetime.now() - start_time).total_seconds(), 2),
                    "success": result.get("success", True),
                    "report_present": bool(result.get("report")),
                })

            self.context.add_turn(
                query=user_query,
                intent=intent.value,
                response=result.get('response', ''),
                metadata=metadata
            )

            if intent in [Intent.CHAT, Intent.REPORT, Intent.FOLLOWUP]:
                result = self._add_chart_marker(result, user_query, metadata, resolved_query)

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
            if capture_thinking and thinking_steps is not None:
                error_step = self._add_thinking_step(
                    thinking_steps,
                    "error",
                    "处理失败"
                )
                error_step["result"] = {"error": str(e)}
                error_result['thinking'] = thinking_steps
            return error_result

    def _handle_chat(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理快速对话"""
        if self.llm:
            return self.chat_handler.handle_with_llm(query, metadata, self.context)
        return self.chat_handler.handle(query, metadata, self.context)


    async def _handle_report_async(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Async report path - 统一走 Supervisor → Forum 流程"""
        if not self.supervisor:
            return {
                'success': False,
                'response': '报告生成服务不可用，请检查 Supervisor 配置。',
                'intent': 'report',
            }
        
        tickers = metadata.get('tickers', [])
        if not tickers:
            return {
                'success': False,
                'response': '请指定要分析的股票代码，例如：分析 AAPL',
                'intent': 'report',
            }
        
        ticker = tickers[0]
        try:
            supervisor_result = await self.supervisor.process(
                query=query,
                tickers=[ticker],
                user_profile=None,
                context_summary=self.context.get_summary(),
                context_ticker=self.context.current_focus,
            )

            response_text = str(supervisor_result.response) if supervisor_result.response is not None else ""
            report_payload = None
            try:
                if supervisor_result.intent and getattr(supervisor_result.intent, "value", "") == "report":
                    if supervisor_result.forum_output:
                        report_payload = self.supervisor._build_report_ir(
                            supervisor_result,
                            ticker,
                            supervisor_result.classification,
                        )
                    elif response_text:
                        report_payload = self.supervisor._build_fallback_report(
                            supervisor_result,
                            ticker,
                            supervisor_result.classification,
                        )
            except Exception as exc:
                logger.info(f"[Agent] build report payload failed: {exc}")

            converted = self._convert_supervisor_result(supervisor_result)
            converted["report"] = report_payload
            converted["method"] = "supervisor"
            return converted
        except Exception as e:
            logger.error(f"[Agent] Supervisor async call failed: {e}")
            return {
                'success': False,
                'response': f'?????????: {str(e)}',
                'intent': 'report',
            }

    def _handle_report(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理报告请求 - 统一走 Supervisor 流程"""
        if not self.supervisor:
            return {
                'success': False,
                'response': '报告生成服务不可用，请检查 Supervisor 配置。',
                'intent': 'report',
            }
        
        tickers = metadata.get('tickers', [])
        if not tickers:
            return {
                'success': False,
                'response': '请指定要分析的股票代码，例如：分析 AAPL',
                'intent': 'report',
            }
        
        # 尝试异步执行
        try:
            asyncio.get_running_loop()
            logger.info(f"[Agent._handle_report] 已有事件循环，无法同步调用 Supervisor")
            return {
                'success': False,
                'response': '请使用流式接口 /api/chat 生成报告',
                'intent': 'report',
            }
        except RuntimeError:
            return asyncio.run(self._handle_report_async(query, metadata))

    def _handle_alert(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理监控请求（待实现）"""
        tickers = metadata.get('tickers', [])
        ticker = tickers[0] if tickers else None
        explicit_company = bool(metadata.get('company_names') or metadata.get('company_mentions'))
        if not ticker and self.context.current_focus and not explicit_company:
            ticker = self.context.current_focus
        if explicit_company and not ticker:
            return self.chat_handler._handle_company_clarification(query, metadata)

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

    def _handle_economic_events(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理经济日历/宏观事件查询"""
        return self.chat_handler._handle_economic_events(query, self.context)

    def _handle_news_sentiment(self, query: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """处理新闻情绪/舆情查询"""
        tickers = metadata.get('tickers', [])
        ticker = tickers[0] if tickers else None
        explicit_company = bool(metadata.get('company_names') or metadata.get('company_mentions'))
        if not ticker and self.context.current_focus and not explicit_company:
            ticker = self.context.current_focus
        if explicit_company and not ticker:
            return self.chat_handler._handle_company_clarification(query, metadata)
        return self.chat_handler._handle_news_sentiment_query(ticker, query, self.context)

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
        """Handle clarification requests (SchemaRouter only)."""
        if metadata.get("schema_action") == "clarify":
            question = metadata.get("schema_question") or "clarify_required"
            return {
                'success': True,
                'response': question,
                'intent': 'clarify',
                'needs_clarification': True,
                'schema_tool_name': metadata.get("schema_tool_name"),
                'schema_missing': metadata.get("schema_missing"),
                'source': metadata.get("source", "schema_router"),
            }

        logger.info("[ConversationAgent] Clarify intent without schema_action; fallback to chat handler")
        return self._handle_chat(query, metadata)

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
            if intent in {'greeting', 'clarify', 'followup', 'alert', 'economic_events', 'news_sentiment', 'market_sentiment'}:
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
                    logger.info(f"[Agent] 自动添加图表标记: {chart_marker}")

        except Exception as e:
            logger.info(f"[Agent] 添加图表标记失败: {e}")

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
            'intents': {
                'chat': 0,
                'report': 0,
                'alert': 0,
                'economic_events': 0,
                'news_sentiment': 0,
                'followup': 0,
                'clarify': 0,
                'greeting': 0,
            },
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

    # 初始化 LLM（使用统一的工厂函数，历史遗留代码已提取到 llm_config.py）
    if use_llm:
        try:
            from backend.llm_config import create_llm
            llm = create_llm(
                provider="gemini_proxy",
                temperature=0.3,
                max_tokens=4000,
                request_timeout=300,
            )
            logger.info("[ConversationAgent] LLM 初始化成功")
        except Exception as e:
            logger.info(f"[ConversationAgent] 初始化 LLM 失败: {e}")
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
            logger.info(f"[ConversationAgent] 初始化 Orchestrator 失败: {e}")

    # 初始化 Report Agent
    if use_report_agent:
        try:
            from backend.langchain_agent import create_financial_agent
            report_agent = create_financial_agent()
            logger.info("[ConversationAgent] Report Agent 初始化成功")
        except Exception as e:
            logger.info(f"[ConversationAgent] 初始化 Report Agent 失败: {e}")
            import traceback
            traceback.print_exc()

    # 初始化 Agent Supervisor (New in Phase 1)
    if llm and orchestrator:
        try:
            from backend.orchestration.supervisor_agent import SupervisorAgent
            # 需要传入 cache 和 circuit_breaker
            supervisor = SupervisorAgent(
                llm=llm,
                tools_module=orchestrator.tools_module, # Bridge 注册后的 module
                cache=orchestrator.cache,
                circuit_breaker=orchestrator.circuit_breaker
            )
            logger.info("[ConversationAgent] Agent Supervisor 初始化成功")
        except Exception as e:
            logger.info(f"[ConversationAgent] 初始化 Supervisor 失败: {e}")

    return ConversationAgent(
        llm=llm,
        orchestrator=orchestrator,
        report_agent=report_agent,
        supervisor=supervisor
    )
