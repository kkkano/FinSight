# -*- coding: utf-8 -*-
"""
ReportHandler - 深度报告处理器
生成专业的投资分析报告
"""

import sys
import os
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class ReportHandler:
    """
    深度报告处理器
    
    用于生成专业投资报告：
    - 完整的数据收集流程
    - 结构化的报告格式
    - 800+ 字的详细分析
    
    响应时间目标: 30-60 秒
    """
    
    def __init__(self, agent=None, orchestrator=None, llm=None):
        """
        初始化处理器
        
        Args:
            agent: LangChain Agent 实例（用于完整分析流程）
            orchestrator: ToolOrchestrator 实例
            llm: LLM 实例
        """
        self.agent = agent
        self.orchestrator = orchestrator
        self.llm = llm
        self._init_tools()
    
    def _init_tools(self):
        """初始化工具函数"""
        # 优先从 orchestrator 获取 tools_module
        if self.orchestrator and self.orchestrator.tools_module:
            self.tools_module = self.orchestrator.tools_module
            print("[ReportHandler] 从 orchestrator 获取 tools 模块")
            return
        
        # 回退：直接导入
        try:
            from backend import tools
            self.tools_module = tools
            print("[ReportHandler] 成功从 backend.tools 导入")
        except ImportError:
            try:
                import tools
                self.tools_module = tools
                print("[ReportHandler] 成功从 tools 导入")
            except ImportError as e:
                self.tools_module = None
                print(f"[ReportHandler] 警告: 无法导入 tools 模块: {e}")
    
    def _run_deepsearch(self, query: str, ticker: str):
        """Run DeepSearchAgent synchronously and return AgentOutput (or None)."""
        if not self.llm or not self.tools_module or not self.orchestrator:
            return None
        try:
            from backend.agents.deep_search_agent import DeepSearchAgent

            cache = getattr(self.orchestrator, "cache", None)
            circuit_breaker = getattr(self.orchestrator, "circuit_breaker", None)
            agent = DeepSearchAgent(self.llm, cache, self.tools_module, circuit_breaker)
            print(f"[ReportHandler] DeepSearch start: {ticker}")
            result = asyncio.run(agent.research(query, ticker))
            print(f"[ReportHandler] DeepSearch done: evidence={len(getattr(result, 'evidence', []))}")
            return result
        except Exception as e:
            print(f"[ReportHandler] DeepSearch failed: {e}")
            return None

    def _serialize_evidence(self, evidence: List[Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for ev in evidence or []:
            try:
                items.append({
                    "title": getattr(ev, "title", None),
                    "text": getattr(ev, "text", ""),
                    "source": getattr(ev, "source", ""),
                    "url": getattr(ev, "url", None),
                    "timestamp": getattr(ev, "timestamp", None),
                    "confidence": getattr(ev, "confidence", None),
                    "meta": getattr(ev, "meta", {}) or {},
                })
            except Exception:
                continue
        return items

    def _serialize_agent_output(self, output: Any) -> Dict[str, Any]:
        if not output:
            return {}
        return {
            "agent_name": getattr(output, "agent_name", ""),
            "summary": getattr(output, "summary", ""),
            "confidence": getattr(output, "confidence", None),
            "data_sources": getattr(output, "data_sources", []),
            "as_of": getattr(output, "as_of", None),
            "fallback_used": getattr(output, "fallback_used", False),
            "risks": getattr(output, "risks", []),
            "evidence": self._serialize_evidence(getattr(output, "evidence", [])),
            "trace": getattr(output, "trace", []),
        }

    def _build_citations_from_evidence(self, evidence: List[Any], prefix: str) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        seen = set()
        idx = 1
        for ev in evidence or []:
            if isinstance(ev, dict):
                url = ev.get("url") or ""
                title = ev.get("title") or ev.get("text") or "Source"
                snippet = ev.get("text") or ""
                published_date = ev.get("timestamp") or ""
            else:
                url = getattr(ev, "url", None) or ""
                title = getattr(ev, "title", None) or getattr(ev, "text", "") or "Source"
                snippet = getattr(ev, "text", "") or ""
                published_date = getattr(ev, "timestamp", "") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append({
                "source_id": f"{prefix}-{idx}",
                "title": title[:160],
                "url": url,
                "snippet": snippet[:260],
                "published_date": published_date,
            })
            idx += 1
        return citations

    def handle(
        self, 
        query: str, 
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        处理报告生成请求
        
        Args:
            query: 用户查询
            metadata: 提取的元数据
            context: 对话上下文
            
        Returns:
            响应字典，包含完整的分析报告
        """
        tickers = metadata.get('tickers', [])
        explicit_company = bool(metadata.get('company_names') or metadata.get('company_mentions'))
        company_hint = None
        if explicit_company:
            if metadata.get('company_names'):
                company_hint = metadata.get('company_names')[0]
            elif metadata.get('company_mentions'):
                company_hint = metadata.get('company_mentions')[0]

        if explicit_company and not tickers and company_hint:
            if self.tools_module and hasattr(self.tools_module, 'resolve_company_ticker'):
                try:
                    resolution = self.tools_module.resolve_company_ticker(company_hint)
                    matches = resolution.get('matches') if isinstance(resolution, dict) else []
                    if matches:
                        if len(matches) == 1 and matches[0].get('symbol'):
                            tickers = [matches[0]['symbol']]
                            metadata['tickers'] = tickers
                            metadata['ticker_resolution'] = resolution
                        else:
                            selected = self._select_candidate_by_hint(query, matches, context)
                            if selected and selected.get('symbol'):
                                tickers = [selected['symbol']]
                                metadata['tickers'] = tickers
                                metadata['ticker_resolution'] = resolution
                                matches = []
                            if matches:
                                options = []
                                for item in matches[:5]:
                                    symbol = item.get('symbol') if isinstance(item, dict) else str(item)
                                    desc = item.get('description') if isinstance(item, dict) else ''
                                    line = '- ' + symbol
                                    if desc:
                                        line += ' (' + desc + ')'
                                    options.append(line)
                                return {
                                    'success': True,
                                    'response': '我找到了多个可能的股票代码，和“' + str(company_hint) + '”相关，请确认一个：\n' + '\n'.join(options) + '\n\n你也可以直接说“美股/法股/港股/英股”等市场偏好。',
                                    'needs_clarification': True,
                                    'intent': 'report',
                                }
                except Exception as e:
                    print('[ReportHandler] ticker lookup failed: ' + str(e))

        if not tickers and context and context.current_focus and not explicit_company:
            tickers = [context.current_focus]

        if not tickers:
            return {
                'success': True,
                'response': self._generate_clarification_response(metadata),
                'needs_clarification': True,
                'intent': 'report',
            }
        
        ticker = tickers[0]
        
        # 注意：之前这里有一个"确认机制"，询问用户想分析哪些方面
        # 但这个机制有问题：用户输入数字（如"6"）后，会被 LLM 路由器
        # 识别为 FOLLOWUP 意图而非 REPORT，导致走错误的处理路径
        # 因此直接删除，生成完整的综合分析报告

        
        # 优先使用现有的 Agent 进行完整分析
        if self.agent:
            try:
                return self._handle_with_agent(ticker, query, context)
            except Exception as e:
                print(f"[ReportHandler] Agent 处理失败，回退到数据收集模式: {e}")
                # 继续执行回退逻辑
        
        # 如果没有 Agent 或 Agent 失败，使用数据收集 + LLM 生成
        if self.llm and self.tools_module:
            try:
                return self._handle_with_data_collection(ticker, query, context)
            except Exception as e:
                print(f"[ReportHandler] LLM 数据收集模式失败: {e}")
                # 继续执行最终回退逻辑
        
        # 最终回退：使用 orchestrator 或 tools_module 直接收集数据，生成简化报告
        if self.orchestrator or self.tools_module:
            try:
                return self._handle_with_basic_data_collection(ticker, query, context)
            except Exception as e:
                print(f"[ReportHandler] 基础数据收集失败: {e}")
        
        return {
            'success': False,
            'response': "报告生成器暂不可用，请检查配置。\n\n可能的原因：\n1. LLM 未正确初始化\n2. 工具模块未加载\n3. 数据源不可用\n\n请检查后端日志获取详细信息。",
            'error': 'agent_not_available',
            'intent': 'report',
        }
    
    def _handle_with_agent(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """使用现有 Agent 进行完整分析 (Phase 2 Upgrade: Supervisor + Forum + ReportIR)"""
        print(f"[ReportHandler._handle_with_agent] 开始处理 ticker={ticker}")
        try:
            # Phase 2 Supervisor 调用 - 暂时禁用
            # 原因：asyncio.run() 不能在 FastAPI 的事件循环中调用
            # 真正的解决方案需要异步化整个调用链（ConversationAgent -> ReportHandler -> Supervisor）
            # 这是 Phase 2 重构任务，目前直接使用 Legacy Logic（self.agent.analyze）
            use_supervisor = False  # 暂时禁用
            
            if use_supervisor:
                from backend.orchestration.supervisor import AgentSupervisor
                from backend.services.memory import UserProfile
                from backend.report.ir import ReportIR
                from backend.report.validator import ReportValidator

                # 初始化 Supervisor
                # 注意：这里我们重用 self.llm 和 self.tools_module
                # 如果没有 Supervisor 实例，我们创建一个
                if not hasattr(self, 'supervisor') or not self.supervisor:
                    # 获取缓存和熔断器 (如果 orchestrator 有)
                    cache = getattr(self.orchestrator, 'cache', None)
                    circuit_breaker = getattr(self.orchestrator, 'circuit_breaker', None)

                    self.supervisor = AgentSupervisor(
                        llm=self.llm,
                        tools_module=self.tools_module,
                        cache=cache,
                        circuit_breaker=circuit_breaker
                    )

                # 准备用户画像 (从 context 获取，暂为 Mock)
                user_profile = UserProfile(
                    user_id="current_user",
                    risk_tolerance="medium",
                    investment_style="balanced"
                )

                # 执行分析 (Supervisor -> Forum -> Output)
                analysis_result = asyncio.run(self.supervisor.analyze(query, ticker, user_profile))
                forum_output = analysis_result.get("forum_output")

                # 构建 ReportIR (简单转换，实际应由专门的 Mapper 完成)
                report_ir = self._convert_to_report_ir(
                    ticker,
                    query,
                    forum_output,
                    analysis_result.get("agent_outputs"),
                )

                # 校验 IR
                report_ir_dict = ReportValidator.validate_and_fix(report_ir)

                return {
                    'success': True,
                    'response': forum_output.consensus, # 简短文本回复
                    'data': analysis_result,
                    'report': report_ir_dict, # 关键：返回结构化报告数据供前端渲染
                    'intent': 'report',
                    'method': 'supervisor_v2',
                }

            # Legacy Logic (原有的 Agent 调用)
            # 构建分析查询
            analysis_query = f"请对 {ticker} 进行深度投资分析"
            if query != analysis_query:
                analysis_query = query  # 使用原始查询

            # 调用 Agent
            result = self.agent.analyze(analysis_query)
            deepsearch_output = self._run_deepsearch(analysis_query, ticker)
            deepsearch_payload = self._serialize_agent_output(deepsearch_output) if deepsearch_output else {}
            citations = (
                self._build_citations_from_evidence(getattr(deepsearch_output, "evidence", []), "DS")
                if deepsearch_output else []
            )

            if isinstance(result, dict):
                output = result.get('output', '')
                success = result.get('success', False)

                # 缓存分析结果到上下文
                if context and success:
                    context.cache_data(f'report:{ticker}', output)

                # 生成 ReportIR 供前端渲染
                report_ir = self._generate_simple_report_ir(
                    ticker,
                    output,
                    citations=citations,
                    meta={"deep_search": deepsearch_payload} if deepsearch_payload else {},
                )
                data_payload = result
                if deepsearch_payload:
                    data_payload = dict(result)
                    data_payload["deep_search"] = deepsearch_payload
                
                return {
                    'success': success,
                    'response': output,
                    'data': data_payload,
                    'report': report_ir,  # 关键：添加 report 字段
                    'intent': 'report',
                    'method': 'agent',
                }
            else:
                output_str = str(result)
                report_ir = self._generate_simple_report_ir(
                    ticker,
                    output_str,
                    citations=citations,
                    meta={"deep_search": deepsearch_payload} if deepsearch_payload else {},
                )
                
                return {
                    'success': True,
                    'response': output_str,
                    'data': {"deep_search": deepsearch_payload} if deepsearch_payload else {},
                    'report': report_ir,  # 关键：添加 report 字段
                    'intent': 'report',
                    'method': 'agent',
                }

        except Exception as e:
            return {
                'success': False,
                'response': f"生成报告时出错: {str(e)}",
                'error': str(e),
                'intent': 'report',
            }

    def _convert_to_report_ir(
        self,
        ticker: str,
        query: str,
        forum_output: Any,
        agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """将 ForumOutput 转换为 ReportIR 字典 (Helper)"""
        from datetime import datetime
        from backend.report.validator import ReportValidator

        # Use os.linesep to avoid syntax errors with literal newlines in strings
        # This is safer than embedding newlines directly in source code
        risk_list_str = os.linesep.join([f"- {r}" for r in forum_output.risks])
        risk_text = f"风险因素:{os.linesep}{risk_list_str}"

        citations: List[Dict[str, Any]] = []
        agent_traces: Dict[str, Any] = {}
        if agent_outputs and isinstance(agent_outputs, dict):
            for name, output in agent_outputs.items():
                prefix = str(name).upper()[:2] if name else "AG"
                citations.extend(self._build_citations_from_evidence(getattr(output, "evidence", []), prefix))
                trace = getattr(output, "trace", None)
                if trace:
                    agent_traces[name] = trace

        report = {
            "report_id": f"rpt_{ticker}_{int(datetime.now().timestamp())}",
            "ticker": ticker,
            "company_name": ticker, # 暂用 Ticker 代替
            "title": f"{ticker} Investment Analysis",
            "summary": forum_output.consensus,
            "sentiment": "bullish" if "BUY" in forum_output.recommendation else "bearish" if "SELL" in forum_output.recommendation else "neutral",
            "confidence_score": forum_output.confidence,
            "generated_at": datetime.now().isoformat(),
            "sections": [
                {
                    "title": "核心观点 (Consensus)",
                    "order": 1,
                    "contents": [{"type": "text", "content": forum_output.consensus}]
                },
                {
                    "title": "分歧与风险 (Disagreement & Risks)",
                    "order": 2,
                    "contents": [
                        {"type": "text", "content": forum_output.disagreement},
                        {"type": "text", "content": risk_text}
                    ]
                },
                {
                    "title": "投资建议 (Recommendation)",
                    "order": 3,
                    "contents": [{"type": "text", "content": f"建议: {forum_output.recommendation}"}]
                }
            ],
            "citations": citations,
            "risks": forum_output.risks,
            "recommendation": forum_output.recommendation,
            "meta": {"agent_traces": agent_traces} if agent_traces else {},
        }
        return ReportValidator.validate_and_fix(report, as_dict=True)
    
    def _handle_with_data_collection(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """使用数据收集 + LLM 生成报告"""
        try:
            # 1. 收集数据
            collected_data = self._collect_data(ticker, context)
            
            if not collected_data.get('price'):
                return {
                    'success': False,
                    'response': f"无法获取 {ticker} 的基本数据，报告生成失败。",
                    'error': 'data_collection_failed',
                    'intent': 'report',
                }
            
            # 2. 使用 LLM 生成报告
            report = self._generate_report_with_llm(ticker, collected_data, query)
            
            # 3. 缓存报告
            if context:
                context.cache_data(f'report:{ticker}', report)
            
            # 4. 生成 ReportIR 供前端渲染
            report_ir = self._generate_simple_report_ir(ticker, report)
            
            return {
                'success': True,
                'response': report,
                'data': collected_data,
                'report': report_ir,  # 关键：添加 report 字段
                'intent': 'report',
                'method': 'data_collection_llm',
            }
        
        except Exception as e:
            return {
                'success': False,
                'response': f"生成报告时出错: {str(e)}",
                'error': str(e),
                'intent': 'report',
            }
    
    def _handle_with_basic_data_collection(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        使用基础数据收集生成简化报告（无 LLM）
        这是最终回退方案
        """
        try:
            # 1. 收集数据
            collected_data = self._collect_data(ticker, context)
            
            if not collected_data.get('price'):
                return {
                    'success': False,
                    'response': f"无法获取 {ticker} 的基本数据，报告生成失败。",
                    'error': 'data_collection_failed',
                    'intent': 'report',
                }
            
            # 2. 生成简化报告（不使用 LLM）
            report = self._generate_fallback_report(ticker, collected_data)
            
            # 3. 缓存报告
            if context:
                context.cache_data(f'report:{ticker}', report)
            
            # 4. 生成 ReportIR 供前端渲染
            report_ir = self._generate_simple_report_ir(ticker, report)
            
            return {
                'success': True,
                'response': report,
                'data': collected_data,
                'report': report_ir,  # 关键：添加 report 字段
                'intent': 'report',
                'method': 'basic_data_collection',
            }
        
        except Exception as e:
            return {
                'success': False,
                'response': f"生成报告时出错: {str(e)}",
                'error': str(e),
                'intent': 'report',
            }
    
    def _collect_data(self, ticker: str, context: Optional[Any] = None) -> Dict[str, Any]:
        """收集分析所需的数据"""
        data = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
        }
        
        # 1. 获取价格
        try:
            if self.orchestrator:
                result = self.orchestrator.fetch('price', ticker)
                if result.success:
                    data['price'] = result.data
                    data['price_source'] = result.source
            elif self.tools_module:
                data['price'] = self.tools_module.get_stock_price(ticker)
        except Exception as e:
            print(f"[ReportHandler] 获取价格失败: {e}")
        
        # 2. 获取公司信息
        try:
            if self.tools_module:
                data['company_info'] = self.tools_module.get_company_info(ticker)
        except Exception as e:
            print(f"[ReportHandler] 获取公司信息失败: {e}")
        
        # 3. 获取新闻
        try:
            if self.tools_module:
                data['news'] = self.tools_module.get_company_news(ticker)
        except Exception as e:
            print(f"[ReportHandler] 获取新闻失败: {e}")
        
        # 4. 获取市场情绪
        try:
            if self.tools_module:
                data['sentiment'] = self.tools_module.get_market_sentiment()
        except Exception as e:
            print(f"[ReportHandler] 获取情绪失败: {e}")
        
        # 5. 获取表现对比 (YTD/1Y)
        try:
            if self.tools_module and hasattr(self.tools_module, "get_performance_comparison"):
                benchmark = os.getenv("DEFAULT_BENCHMARK_TICKER", "").strip()
                benchmark_label = os.getenv("DEFAULT_BENCHMARK_LABEL", "").strip() or benchmark
                tickers_map = {ticker: ticker}
                if benchmark and benchmark.lower() not in ("none", "off", "false", "0"):
                    tickers_map[benchmark_label] = benchmark
                data["performance_comparison"] = self.tools_module.get_performance_comparison(tickers_map)
        except Exception as e:
            print(f"[ReportHandler] 获取表现对比失败: {e}")

        # 6. 历史回撤分析
        try:
            if self.tools_module and hasattr(self.tools_module, "analyze_historical_drawdowns"):
                data["drawdown_analysis"] = self.tools_module.analyze_historical_drawdowns(ticker)
        except Exception as e:
            print(f"[ReportHandler] 历史回撤分析失败: {e}")

        # 7. 搜索上下文补充
        try:
            if self.tools_module:
                data['search_context'] = self.tools_module.search(
                    f"{ticker} stock analysis latest news {datetime.now().strftime('%B %Y')}"
                )
        except Exception as e:
            print(f"[ReportHandler] 搜索失败: {e}")
        
        return data
    
    def _generate_report_with_llm(
        self, 
        ticker: str, 
        data: Dict[str, Any],
        original_query: str
    ) -> str:
        """使用 LLM 生成报告"""
        from langchain_core.messages import HumanMessage
        from backend.prompts.system_prompts import REPORT_SYSTEM_PROMPT
        
        # 构建数据摘要
        data_summary = self._format_data_for_llm(data)
        
        # 填充提示词
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        prompt = REPORT_SYSTEM_PROMPT.format(
            current_date=current_date,
            query=original_query,
            accumulated_data=data_summary,
            tools="(数据已预先收集)"
        )
        
        # 添加生成指令
        prompt += f"""

Based on the collected data above, generate a comprehensive investment analysis report for {ticker}.

The report MUST:
1. Be at least 800 words
2. Include all mandatory sections
3. Reference specific data points
4. Provide actionable recommendations

BEGIN REPORT:"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            # 生成简化报告
            return self._generate_fallback_report(ticker, data)
    
    def _format_data_for_llm(self, data: Dict[str, Any]) -> str:
        """格式化数据供 LLM 使用"""
        sections = []
        
        if data.get('price'):
            sections.append(f"## Price Data\n{data['price']}")
        
        if data.get('company_info'):
            sections.append(f"## Company Information\n{data['company_info']}")
        
        if data.get('news'):
            sections.append(f"## Recent News\n{data['news']}")
        
        if data.get('sentiment'):
            sections.append(f"## Market Sentiment\n{data['sentiment']}")
        
        if data.get('performance_comparison'):
            sections.append(f"## Performance Comparison\n{data['performance_comparison']}")

        if data.get('drawdown_analysis'):
            sections.append(f"## Drawdown Analysis\n{data['drawdown_analysis']}")

        if data.get('search_context'):
            # 截取搜索结果的前 500 字符
            search_preview = data['search_context'][:500] + "..." if len(data['search_context']) > 500 else data['search_context']
            sections.append(f"## Additional Context\n{search_preview}")
        
        return "\n\n".join(sections)
    
    def _generate_fallback_report(self, ticker: str, data: Dict[str, Any]) -> str:
        """生成简化的备用报告"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        report = f"""# {ticker} - Investment Analysis Report
*Report Date: {current_date}*

## EXECUTIVE SUMMARY

This is a simplified analysis report for {ticker}. Due to technical limitations, a full AI-generated analysis could not be completed.

## CURRENT MARKET POSITION

"""
        if data.get('price'):
            report += f"{data['price']}\n\n"
        else:
            report += "Price data unavailable.\n\n"
        
        if data.get('company_info'):
            report += f"## COMPANY PROFILE\n\n{data['company_info']}\n\n"
        
        if data.get('news'):
            report += f"## RECENT NEWS\n\n{data['news']}\n\n"
        
        if data.get('sentiment'):
            report += f"## MARKET SENTIMENT\n\n{data['sentiment']}\n\n"
        
        report += """## DISCLAIMER

This is a simplified report. For comprehensive investment advice, please consult a qualified financial advisor.

---
*Generated by FinSight AI*
"""
        return report
    
    def _generate_simple_report_ir(
        self,
        ticker: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        从纯文本生成简化的 ReportIR 结构
        用于 Legacy 路径，确保前端能渲染 Report 卡片
        """
        import re
        from backend.report.validator import ReportValidator
        
        # 尝试从内容中提取章节
        sections = []
        
        # 匹配 Markdown 标题 (## 或 ###)
        section_pattern = r'^#{2,3}\s+(.+?)$'
        parts = re.split(section_pattern, content, flags=re.MULTILINE)
        
        order = 1
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                title = parts[i].strip()
                body = parts[i + 1].strip()
                if title and body:
                    sections.append({
                        "title": title,
                        "order": order,
                        "contents": [{"type": "text", "content": body}]
                    })
                    order += 1
        
        # 如果没有解析到章节，将整个内容作为摘要
        if not sections:
            sections = [{
                "title": "分析摘要",
                "order": 1,
                "contents": [{"type": "text", "content": content[:2000]}]  # 限制长度
            }]
        
        # 尝试提取摘要（第一段或前 200 字）
        first_para = content.split('\n\n')[0] if '\n\n' in content else content[:200]
        summary = first_para[:300] + "..." if len(first_para) > 300 else first_para
        
        # 推断情绪
        content_lower = content.lower()
        if any(kw in content_lower for kw in ['bullish', '看涨', '买入', 'buy', '增持', '强烈推荐']):
            sentiment = 'bullish'
        elif any(kw in content_lower for kw in ['bearish', '看跌', '卖出', 'sell', '减持', '谨慎']):
            sentiment = 'bearish'
        else:
            sentiment = 'neutral'
        
        report = {
            "report_id": f"rpt_{ticker}_{int(datetime.now().timestamp())}",
            "ticker": ticker,
            "company_name": ticker,
            "title": f"{ticker} 深度投资分析报告",
            "summary": summary,
            "sentiment": sentiment,
            "confidence_score": 0.75,  # 默认置信度
            "generated_at": datetime.now().isoformat(),
            "sections": sections,
            "citations": citations or [],
            "risks": [],
            "recommendation": "HOLD",
            "meta": meta or {},
        }
        return ReportValidator.validate_and_fix(report, as_dict=True)
    
    def _generate_pre_analysis_question(self, ticker: str, original_query: str) -> str:
        """
        生成分析前的确认问题，改进对话体验
        """
        return f"""好的，我准备为您生成 **{ticker}** 的深度分析报告。

在开始之前，我想了解一下您最关心的方面，这样我可以为您提供更有针对性的分析：

**您希望我重点关注哪些方面？**

1. 📈 **价格走势和技术分析** - K线图、技术指标、支撑阻力位
2. 💼 **基本面分析** - 财务数据、盈利能力、估值水平
3. 📰 **新闻和事件** - 最新动态、市场情绪、催化剂
4. ⚠️ **风险评估** - 潜在风险、波动性分析
5. 💡 **投资策略** - 进出场建议、目标价位
6. 📊 **综合全面分析** - 以上所有方面（完整报告）

您可以直接说数字（如"1"或"1和3"），或者描述您的需求（如"重点关注价格走势和风险"）。

如果不需要特别指定，我也可以直接生成**综合全面分析报告**。您希望如何继续？"""
    
    def _generate_clarification_response(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """生成澄清请求"""
        metadata = metadata or {}
        company_names = metadata.get('company_names') or []
        hint_line = ""
        if company_names:
            hint_line = f"我识别到可能的公司名：{company_names[0]}。如果是它，请确认并给出股票代码。\n\n"

        return f"""为了生成深度报告，请告诉我具体标的。

{hint_line}你可以提供：
1. 股票代码（如 AAPL, TSLA, NVDA）
2. 公司名称（如 苹果/特斯拉/英伟达）
3. 指数或 ETF（如 标普500/纳斯达克100/SPY）

示例：
- "分析 AAPL"
- "做一份特斯拉研报"
- "标普500 深度分析"

请告诉我要分析的目标。"""

    def _select_candidate_by_hint(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        context: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        market_hint = self._extract_market_hint(query)
        if not market_hint and context is not None:
            market_hint = getattr(context, "market_preference", None)
        if not market_hint:
            return None
        for item in candidates:
            if self._candidate_matches_market(item, market_hint):
                return item
        return None

    def _extract_market_hint(self, query: str) -> Optional[str]:
        lowered = query.lower()
        hint_map = {
            "US": ["美国", "美股", "nyse", "nasdaq", "otc", "adr", "us", "u.s"],
            "FR": ["法国", "法股", "巴黎", "euronext", "paris", ".pa"],
            "UK": ["英国", "英股", "伦敦", "lse", "london", ".l"],
            "HK": ["香港", "港股", "hkex", ".hk"],
            "CN": ["中国", "a股", "沪", "深", "上证", "深证", "sse", "szse", ".ss", ".sz"],
            "JP": ["日本", "日股", "东京", "tse", ".t"],
            "EU": ["欧洲", "欧股", "eu", "euronext"],
        }
        for market, keys in hint_map.items():
            for key in keys:
                if key.isascii():
                    if key in lowered:
                        return market
                else:
                    if key in query:
                        return market
        return None

    def _candidate_matches_market(self, candidate: Dict[str, Any], market: str) -> bool:
        symbol = (candidate.get("symbol") or "").upper()
        exchange = (candidate.get("primaryExchange") or "").upper()
        description = (candidate.get("description") or "").upper()
        blob = f"{symbol} {exchange} {description}"

        if market == "US":
            return any(tag in blob for tag in ["NYSE", "NASDAQ", "OTC", "US", "ADR"]) or symbol.endswith(".US")
        if market == "FR":
            return any(tag in blob for tag in ["PAR", "EURONEXT", "PARIS"]) or symbol.endswith(".PA")
        if market == "UK":
            return any(tag in blob for tag in ["LSE", "LONDON"]) or symbol.endswith(".L")
        if market == "HK":
            return any(tag in blob for tag in ["HK", "HKEX"]) or symbol.endswith(".HK")
        if market == "CN":
            return any(tag in blob for tag in ["SSE", "SZSE", "SHANGHAI", "SHENZHEN"]) or symbol.endswith((".SS", ".SZ"))
        if market == "JP":
            return any(tag in blob for tag in ["TSE", "TOKYO"]) or symbol.endswith(".T")
        if market == "EU":
            return "EURONEXT" in blob or symbol.endswith(".PA")
        return False
