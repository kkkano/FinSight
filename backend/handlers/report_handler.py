# -*- coding: utf-8 -*-
"""
ReportHandler - 深度报告处理器
生成专业的投资分析报告
"""

import sys
import os
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
        
        # 如果没有股票代码，尝试从上下文获取
        if not tickers and context and context.current_focus:
            tickers = [context.current_focus]
        
        if not tickers:
            return {
                'success': True,
                'response': self._generate_clarification_response(),
                'needs_clarification': True,
                'intent': 'report',
            }
        
        ticker = tickers[0]
        
        # 改进对话体验：先询问用户想要分析哪些方面
        # 检查是否已经确认过（通过上下文判断）
        if context:
            # 检查最近的对话中是否有确认信息
            # ContextManager 使用 turns 列表存储对话历史
            recent_turns = []
            if hasattr(context, 'turns') and context.turns:
                recent_turns = list(context.turns)[-3:]  # 最近3轮对话
            
            has_confirmation = False
            if recent_turns:
                # 检查最近的回复中是否有确认信息，或用户是否已经回答过
                for turn in recent_turns:
                    turn_query = getattr(turn, 'query', '') or ''
                    turn_response = getattr(turn, 'response', '') or ''
                    
                    # 检查用户回复中是否有确认词
                    confirmation_keywords = ['好的', '可以', '开始', '确认', '是的', '行', 'ok', 'yes', '综合', '全面', '全部', '都']
                    if any(keyword in turn_query.lower() for keyword in confirmation_keywords):
                        has_confirmation = True
                        break
                    
                    # 检查AI回复中是否已经询问过
                    if '您希望我重点关注' in turn_response or '您希望如何继续' in turn_response:
                        # 如果AI已经询问过，用户的下一次回复应该被视为确认
                        has_confirmation = True
                        break
            
            # 如果用户明确要求"分析"或"报告"，且没有确认过，先询问
            query_lower = query.lower()
            is_explicit_report_request = any(keyword in query_lower for keyword in ['分析', '报告', '评估', '研究', '深度'])
            
            # 如果用户回复包含数字（1-6）或明确的需求描述，视为已确认
            has_user_preference = any(
                keyword in query_lower for keyword in [
                    '1', '2', '3', '4', '5', '6', '价格', '技术', '基本面', '财务', 
                    '新闻', '风险', '策略', '综合', '全面', '全部'
                ]
            )
            
            if is_explicit_report_request and not has_confirmation and not has_user_preference:
                return {
                    'success': True,
                    'response': self._generate_pre_analysis_question(ticker, query),
                    'needs_confirmation': True,
                    'intent': 'report',
                    'waiting_for_confirmation': True,
                }
        
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
        """使用现有 Agent 进行完整分析"""
        try:
            # 构建分析查询
            analysis_query = f"请对 {ticker} 进行深度投资分析"
            if query != analysis_query:
                analysis_query = query  # 使用原始查询
            
            # 调用 Agent
            result = self.agent.analyze(analysis_query)
            
            if isinstance(result, dict):
                output = result.get('output', '')
                success = result.get('success', False)
                
                # 缓存分析结果到上下文
                if context and success:
                    context.cache_data(f'report:{ticker}', output)
                
                return {
                    'success': success,
                    'response': output,
                    'data': result,
                    'intent': 'report',
                    'method': 'agent',
                }
            else:
                return {
                    'success': True,
                    'response': str(result),
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
            
            return {
                'success': True,
                'response': report,
                'data': collected_data,
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
            
            return {
                'success': True,
                'response': report,
                'data': collected_data,
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
        
        # 5. 搜索补充信息
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
    
    def _generate_clarification_response(self) -> str:
        """生成澄清请求"""
        return """我需要知道您想分析哪支股票。请提供：

1. 股票代码（如 AAPL, TSLA, NVDA）
2. 或公司名称（如 苹果, 特斯拉, 英伟达）

例如：
- "分析 AAPL"
- "帮我分析一下特斯拉"
- "NVDA 值得投资吗？"

请告诉我您想分析的目标。"""
