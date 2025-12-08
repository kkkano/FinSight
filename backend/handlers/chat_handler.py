# -*- coding: utf-8 -*-
"""
ChatHandler - 快速对话处理器
处理简单问题，提供快速简洁的回答

核心修复点:
1. 修复了 _handle_chat_query 的 AttributeError。
2. 移除了 _is_chat_query 中的重复逻辑。
3. 优化了 handle 方法中 query_lower 的定义，避免冗余。
"""

import sys
import os
import random
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime

# 尝试导入 LangChain 核心模块（假设已安装）
try:
    from langchain_core.messages import HumanMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("[ChatHandler] Warning: langchain_core not found. LLM features disabled.")


# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class ChatHandler:
    """
    快速对话处理器
    
    用于处理简单问题如：股价查询、简单的市场状况、快速问答
    响应时间目标: < 10 秒
    响应长度: 2-5 句话
    """
    
    def __init__(self, llm=None, orchestrator=None):
        """
        初始化处理器
        
        Args:
            llm: LLM 实例 (例如 LangChain Runnable)
            orchestrator: ToolOrchestrator 实例
        """
        self.llm = llm
        self.orchestrator = orchestrator
        self.tools_module = None
        self._init_tools()
    
    def _init_tools(self):
        """初始化工具函数"""
        # 优先从 orchestrator 获取 tools_module
        if self.orchestrator and hasattr(self.orchestrator, 'tools_module') and self.orchestrator.tools_module:
            self.tools_module = self.orchestrator.tools_module
            print("[ChatHandler] 从 orchestrator 获取 tools 模块")
            return
        
        # 回退：直接导入
        try:
            # 假设 tools 模块在 backend/tools.py 或项目根目录
            from backend import tools
            self.tools_module = tools
            print("[ChatHandler] 成功从 backend.tools 导入")
        except ImportError:
            try:
                import tools
                self.tools_module = tools
                print("[ChatHandler] 成功从 tools 导入")
            except ImportError as e:
                self.tools_module = None
                print(f"[ChatHandler] 警告: 无法导入 tools 模块: {e}")
    
    def handle(
        self, 
        query: str, 
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        处理查询
        """
        query_lower = query.lower() # 确保在 handle 开始处统一定义
        
        try:
            tickers = metadata.get('tickers', [])
            if not tickers and context and hasattr(context, 'current_focus') and context.current_focus:
                tickers = [context.current_focus]
            primary_ticker = tickers[0] if tickers else None

            # 优先处理新闻意图：有 ticker 直接拉新闻；无 ticker 先用市场泛化新闻，再兜底默认指数
            if self._is_news_query(query_lower):
                if primary_ticker:
                    return self._handle_news_query(primary_ticker, query, context)
                if self.tools_module and hasattr(self.tools_module, "get_market_news_headlines"):
                    try:
                        news_text = self.tools_module.get_market_news_headlines()
                        return {
                            'success': True,
                            'response': news_text,
                            'intent': 'market_news',
                            'data': {'raw_news': news_text}
                        }
                    except Exception as e:
                        print(f"[ChatHandler] market news fallback failed: {e}")
                default_news_ticker = os.getenv("DEFAULT_NEWS_TICKER", "^GSPC")
                return self._handle_news_query(default_news_ticker, query, context)
            
            # 检查是否为对比查询
            if metadata.get('is_comparison') and len(tickers) >= 2:
                return self._handle_comparison_query(tickers, query, metadata, context)
            
            # 如果没有股票代码，尝试从上下文获取
            if not tickers and context and hasattr(context, 'current_focus') and context.current_focus:
                tickers = [context.current_focus]
            
            if not tickers:
                print(f"[ChatHandler] 检查闲聊/建议意图: Query='{query_lower}'")
                
                # 新闻类无 ticker 查询：默认用大盘指数
                if self._is_news_query(query_lower):
                    default_news_ticker = os.getenv("DEFAULT_NEWS_TICKER", "^GSPC")
                    return self._handle_news_query(default_news_ticker, query, context)
                
                if self._is_advice_query(query_lower):
                    print("[ChatHandler] ✅ 命中泛化建议意图（无 ticker）")
                    return self._handle_generic_recommendation(query)
                
                if self._is_chat_query(query_lower):
                    print("[ChatHandler] 🚀 意图命中: 闲聊/问候。")
                    return self._handle_chat_query(query)
                
                print("[ChatHandler] ⚠️ 意图未命中: 闲聊。回退到通用搜索。")
                return self._handle_with_search(query, context)
            
            # 获取第一个股票的信息 (如果 tickers 有内容)
            ticker = primary_ticker or (tickers[0] if tickers else None)
            if not ticker and context and hasattr(context, 'current_focus') and context.current_focus:
                ticker = context.current_focus
            
            # 判断查询类型并获取相应数据
            if self._is_composition_query(query_lower):
                # 成分股/持仓查询
                return self._handle_composition_query(ticker, query, context)
            elif self._is_advice_query(query_lower):
                # 投资建议查询
                return self._handle_advice_query(ticker, query, context)
            elif self._is_price_query(query_lower):
                return self._handle_price_query(ticker, query, context)
            elif self._is_news_query(query_lower):
                return self._handle_news_query(ticker, query, context)
            elif self._is_info_query(query_lower):
                return self._handle_info_query(ticker, query, context)
            else:
                # 默认：如果有上下文焦点，尝试获取价格；否则使用LLM回答（通常是建议）
                if context and hasattr(context, 'current_focus') and context.current_focus:
                    return self._handle_price_query(ticker, query, context)
                else:
                    return self._handle_advice_query(ticker, query, context)
            
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'response': f"系统处理您的请求时出错: {str(e)}",
                'error': str(e),
                'intent': 'error',
                'thinking': f"Critical Error in ChatHandler: {str(e)}"
            }
    
    # --- 意图判断 ---
    
    def _is_price_query(self, query: str) -> bool:
        keywords = ['价格', '股价', '多少钱', '现价', 'price', 'how much', '涨', '跌', '行情', '走势', '表现']
        return any(kw in query for kw in keywords)
    
    def _is_news_query(self, query: str) -> bool:
        keywords = ['新闻', '消息', 'news', '最新', '发生', '事件', '近几天', '最近', '头条', 'headline']
        return any(kw in query for kw in keywords)
    
    def _is_info_query(self, query: str) -> bool:
        keywords = ['公司', '简介', 'company', 'info', '信息', '介绍', '是什么']
        return any(kw in query for kw in keywords)
    
    def _is_composition_query(self, query: str) -> bool:
        keywords = ['包括哪些', '包含哪些', '成分股', '成分', '持仓', '有哪些', '哪些股票', '哪些公司', 
                     'constituent', 'holdings', 'components', 'includes', 'contains']
        return any(kw in query for kw in keywords)
    
    def _is_advice_query(self, query: str) -> bool:
        keywords = ['推荐', '建议', '怎么做', '如何', '应该', '投资', '买入', '卖出', '持有', 'advice', 'recommend', 'should', 
                     '定投', '策略', '操作', '接下来', '这几天', '这几个月', '怎么办', '怎么', '保持', '最近', '现在']
        return any(kw in query for kw in keywords)
        
    def _is_chat_query(self, query_lower: str) -> bool:
        """判断是否为简单的闲聊或问候语"""
        greeting_keywords = ['你好', '您好', '喂', '嗨', 'hello', 'hi']
        identity_keywords = ['你是谁', '你叫什么', '介绍自己', '自我介绍']
        
        # 宽松匹配，移除所有空格后进行匹配
        cleaned_query = query_lower.replace(' ', '').replace('...', '').replace('？', '').replace('?', '')
        
        # 1. 检查问候语
        if any(kw in query_lower for kw in greeting_keywords):
            return True
            
        # 2. 检查身份查询 (使用清理后的输入提高准确性)
        if any(kw in cleaned_query for kw in identity_keywords):
            return True

        # 3. 如果查询很短且没有任何股票代码/指标，也可能是闲聊
        if len(query_lower) < 15 and any(kw in query_lower for kw in ['谢谢', '再见', '好的']):
            return True

        return False
        
    # --- 核心处理方法 ---
    
    def _handle_chat_query(self, query: str) -> Dict[str, Any]:
        """
        处理简单的闲聊和问候（例如：你好，你是谁，谢谢）。
        """
        if any(kw in query for kw in ['你好', '您好', '喂', '嗨', 'hello', 'hi']):
            response = "你好！我是一个金融智能分析助手，可以帮您查询股票价格、分析走势或生成深度报告。请问您想了解哪支股票？"
        elif any(kw in query for kw in ['你是谁', '你叫什么', '介绍自己', '自我介绍']):
            response = "我叫 FinSight Agent，是专为金融市场设计的人工智能。我可以实时获取数据，并利用 LLM 帮您解读复杂的市场信息。请开始提问吧！"
        elif any(kw in query for kw in ['谢谢', '再见', '好的', 'ok', 'bye']):
            response = "不客气，很高兴为您服务！如果您还有其他金融问题，随时可以问我。再见！"
        else:
            response = "很高兴与您交流！请问有什么金融相关的问题我可以帮忙的吗？"

        return {
            'success': True,
            'response': response,
            'intent_detail': 'greeting_chat',
            'metadata': {},
        }
        
    def _handle_price_query(
        self, 
        ticker: str, 
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理价格查询"""
        # 优先使用 Orchestrator (假设 Orchestrator 已经处理了缓存/回退逻辑)
        if self.orchestrator and hasattr(self.orchestrator, 'fetch'):
            try:
                result = self.orchestrator.fetch('price', ticker)
                if result and result.success:
                    price_data = result.data
                    response = self._format_price_response(ticker, price_data, result.source)
                    
                    if context and hasattr(context, 'cache_data'):
                        context.cache_data(f'price:{ticker}', price_data)
                    
                    return {
                        'success': True,
                        'response': response,
                        'data': {
                            'ticker': ticker,
                            'raw_price': price_data,
                            'source': result.source,
                            'data_origin': result.source,
                            'fallback_used': getattr(result, 'fallback_used', False),
                            'tried_sources': getattr(result, 'tried_sources', []),
                            'trace': getattr(result, 'trace', {}),
                            'as_of': getattr(result, 'as_of', None),
                        },
                        'intent': 'market_data',
                        'thinking': f"Fetched price via Orchestrator (Source: {result.source}, fallback_used={getattr(result, 'fallback_used', False)})"
                    }
                elif result:
                    return {
                        'success': False,
                        'response': f"无法获取 {ticker} 的价格信息: {result.error}",
                        'error': result.error,
                        'intent': 'chat',
                        'thinking': f"Orchestrator failed to fetch price: {result.error}"
                    }
            except Exception as e:
                traceback.print_exc()
                print(f"[ChatHandler] Orchestrator price fetch failed: {e}")
        
        # 回退到直接调用 tools
        if self.tools_module and hasattr(self.tools_module, 'get_stock_price'):
            try:
                # 假设 get_stock_price 返回字符串或字典
                price_info = self.tools_module.get_stock_price(ticker)
                return {
                    'success': True,
                    'response': price_info,
                    'data': {'ticker': ticker, 'raw_price': price_info},
                    'intent': 'market_data',
                    'thinking': "Fetched price via direct tools module."
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取 {ticker} 价格时出错: {str(e)}",
                    'error': str(e),
                    'intent': 'chat',
                    'thinking': f"Direct tool call for price failed: {str(e)}"
                }
        
        return {
            'success': False,
            'response': "价格查询工具暂不可用，请检查后端配置。",
            'error': 'tool_not_available',
            'intent': 'chat',
            'thinking': "No price fetching tool available."
        }
    
    def _handle_news_query(
        self, 
        ticker: str, 
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理新闻查询"""
        if self.tools_module and hasattr(self.tools_module, 'get_company_news'):
            try:
                news_info = self.tools_module.get_company_news(ticker)
                
                if context and hasattr(context, 'cache_data'):
                    context.cache_data(f'news:{ticker}', news_info)
                
                return {
                    'success': True,
                    'response': news_info,
                    'data': {'ticker': ticker, 'raw_news': news_info},
                    'intent': 'company_news',
                    'thinking': "Fetched company news via tools module."
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取 {ticker} 新闻时出错: {str(e)}",
                    'error': str(e),
                    'intent': 'chat',
                    'thinking': f"Tool call for news failed: {str(e)}"
                }
        
        return {
            'success': False,
            'response': "新闻查询工具暂不可用。",
            'error': 'tool_not_available',
            'intent': 'chat',
            'thinking': "No news fetching tool available."
        }
    
    def _handle_info_query(
        self, 
        ticker: str, 
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理公司信息查询"""
        if self.tools_module and hasattr(self.tools_module, 'get_company_info'):
            try:
                info = self.tools_module.get_company_info(ticker)
                
                if context and hasattr(context, 'cache_data'):
                    context.cache_data(f'info:{ticker}', info)
                
                return {
                    'success': True,
                    'response': info,
                    'data': {'ticker': ticker, 'raw_info': info},
                    'intent': 'company_info',
                    'thinking': "Fetched company info via tools module."
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取 {ticker} 公司信息时出错: {str(e)}",
                    'error': str(e),
                    'intent': 'chat',
                    'thinking': f"Tool call for company info failed: {str(e)}"
                }
        
        return {
            'success': False,
            'response': "公司信息查询工具暂不可用。",
            'error': 'tool_not_available',
            'intent': 'chat',
            'thinking': "No company info tool available."
        }
    
    def _handle_composition_query(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理成分股/持仓查询（使用搜索工具）"""
        
        if not self.tools_module or not hasattr(self.tools_module, 'search'):
            return {
                'success': False,
                'response': "搜索工具暂不可用，无法查询成分股信息。",
                'error': 'tool_not_available',
                'intent': 'chat',
                'thinking': "No search tool available for composition query."
            }

        try:
            # 优化搜索查询词
            query_lower = query.lower()
            if '纳斯达克' in query or 'nasdaq' in query_lower:
                search_query = "纳斯达克100指数 成分股"
            elif '标普' in query or 's&p' in query_lower:
                search_query = "标普500指数 成分股"
            else:
                search_query = f"{ticker} {query}"
            
            search_result = self.tools_module.search(search_query)
            
            # 使用 LLM 整理搜索结果
            if self.llm and LANGCHAIN_AVAILABLE:
                prompt = f"""You are a professional financial analyst with expertise in stock market indices and their compositions. The user is asking about the composition/holdings of {ticker}.

User Question: {query}
Search Results: {search_result[:3000]}

**CRITICAL REQUIREMENTS - YOU MUST FOLLOW THESE EXACTLY**:
1. Extract EVERY constituent/holding mentioned in the search results.
2. For each constituent, include: Full company name (e.g., "苹果公司"), Stock ticker symbol (e.g., AAPL), and Weight percentage if mentioned (e.g., "约12.5%").
3. Organize: List top holdings first (by weight if available). Use clear numbering or bullet points.
4. DO NOT provide a summary - provide a COMPREHENSIVE LIST.
5. Response must be in Chinese.
"""
                response = self.llm.invoke([HumanMessage(content=prompt)])
                
                return {
                    'success': True,
                    'response': response.content,
                    'data': {'ticker': ticker, 'query_type': 'composition', 'search_result': search_result[:500]},
                    'intent': 'search_composition',
                    'used_search': True,
                    'thinking': "Used search tool and LLM for composition analysis."
                }
            else:
                # 没有 LLM，直接返回搜索结果摘要
                return {
                    'success': True,
                    'response': f"根据搜索结果，关于 {ticker} 的成分股/持仓情况：\n\n{search_result[:800]}...",
                    'data': {'ticker': ticker, 'query_type': 'composition', 'search_result': search_result[:500]},
                    'intent': 'search_composition',
                    'used_search': True,
                    'thinking': "Used search tool; no LLM for summary."
                }
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'response': f"搜索 {ticker} 成分股信息时出错: {str(e)}",
                'error': str(e),
                'intent': 'chat',
                'thinking': f"Composition search failed: {str(e)}"
            }

    def _handle_comparison_query(
        self,
        tickers: List[str],
        query: str,
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理对比查询 (例如 "Nasdaq 和 S&P 500 有什么区别")"""
        ticker1, ticker2 = tickers[0], tickers[1]
        
        if self.llm and LANGCHAIN_AVAILABLE:
            try:
                # 尝试获取价格信息作为上下文 (省略 Orchestrator 调用细节)
                price_info1, price_info2 = "N/A", "N/A"
                if self.orchestrator and hasattr(self.orchestrator, 'fetch'):
                    try:
                        result1 = self.orchestrator.fetch('price', ticker1)
                        if result1 and result1.success: price_info1 = result1.data
                        result2 = self.orchestrator.fetch('price', ticker2)
                        if result2 and result2.success: price_info2 = result2.data
                    except:
                        pass # 忽略获取价格时的异常
                
                context_info = f"\n{ticker1} Current Price: {price_info1}"
                context_info += f"\n{ticker2} Current Price: {price_info2}"
                
                # 使用 LLM 生成对比分析
                prompt = f"""You are a professional financial analyst. The user wants to understand the differences between {ticker1} and {ticker2}.

User Question: {query}
{context_info}

Please provide a detailed comparison analysis, including: Key Differences (composition, sector distribution, risk) and Investment Characteristics.
Requirements: Respond in Chinese, professional but easy to understand.
"""
                response = self.llm.invoke([HumanMessage(content=prompt)])
                
                return {
                    'success': True,
                    'response': response.content,
                    'data': {'ticker1': ticker1, 'ticker2': ticker2, 'query_type': 'comparison'},
                    'intent': 'comparison_analysis',
                    'thinking': "Used LLM for comparison analysis."
                }
            except Exception as e:
                traceback.print_exc()
                print(f"[ChatHandler] LLM comparison analysis failed: {e}")
        
        # LLM 或 LangChain 不可用时的回退
        return {
            'success': True,
            'response': f"关于 {ticker1} 和 {ticker2} 的简单对比：\n\n1. **{ticker1}**: 偏向成长型/科技股。\n2. **{ticker2}**: 通常更加均衡和分散。",
            'data': {'ticker1': ticker1, 'ticker2': ticker2, 'query_type': 'comparison'},
            'intent': 'chat',
            'thinking': "LLM/LangChain unavailable, returned basic comparison."
        }

    def _handle_advice_query(
        self, 
        ticker: str, 
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理投资建议查询"""
        
        if not self.llm or not LANGCHAIN_AVAILABLE:
            return {
                'success': True, 
                'response': f"关于 {ticker}：建议采用定投策略，分散风险。请注意，投资有风险。",
                'intent': 'advice',
                'thinking': "LLM/LangChain unavailable, returned generic advice."
            }

        # 尝试获取当前价格作为参考（可选）
        current_price_info = "N/A"
        if self.orchestrator and hasattr(self.orchestrator, 'fetch'):
            try:
                price_result = self.orchestrator.fetch('price', ticker)
                if price_result and price_result.success:
                    current_price_info = price_result.data
            except:
                pass 
        
        try:
            # 构建上下文信息
            context_info = f"\nCurrent Price Info: {current_price_info}"
            if context and hasattr(context, 'current_focus') and context.current_focus:
                context_info += f"\nCurrently Focused Asset: {context.current_focus}"
            
            # 使用 LLM 生成建议
            prompt = f"""You are a professional financial investment advisor. The user is asking for investment advice regarding {ticker}.

User Question: {query}
{context_info}

**CRITICAL REQUIREMENTS - YOU MUST FOLLOW THESE EXACTLY**:
1. Understand User Intent (already invested vs preparing to invest).
2. Provide specific, actionable investment advice (e.g., continue holding, add positions, invest in 3-5 batches). 
3. Include a brief Market Analysis (2-3 sentences).
4. Include a clear Risk Warning at the end.
5. **Response MUST be in Chinese**, friendly and helpful tone.
6. Add the following required text at the end exactly: \n\n⚠️ **AI生成建议提示**：以上建议由AI生成，仅供参考，不构成投资建议。投资有风险，请根据自身情况谨慎决策。
"""
            response = self.llm.invoke([HumanMessage(content=prompt)])
            
            return {
                'success': True,
                'response': response.content,
                'data': {'ticker': ticker, 'query_type': 'advice', 'price_info': current_price_info},
                'intent': 'advice',
                'thinking': "Used LLM to generate specific investment advice."
            }
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'response': f"生成投资建议时失败: {str(e)}",
                'error': str(e),
                'intent': 'chat',
                'thinking': f"LLM advice generation failed: {str(e)}"
            }

    def _handle_generic_recommendation(self, query: str) -> Dict[str, Any]:
        """
        无 ticker 的泛化推荐，确保“推荐几只股票”类问题可用。
        """
        picks = [
            {"ticker": "NVDA", "reason": "AI 硬件龙头，盈利高增长", "risk": "估值偏高，波动较大"},
            {"ticker": "MSFT", "reason": "云/AI 双驱动，订阅业务稳定", "risk": "宏观与估值压力"},
            {"ticker": "AAPL", "reason": "消费电子龙头，现金流稳健", "risk": "硬件周期与监管"},
            {"ticker": "VOO", "reason": "S&P500 ETF，被动分散低成本", "risk": "跟随美股整体波动"},
        ]
        lines = [f"- {p['ticker']}: {p['reason']}（风险：{p['risk']}）" for p in picks]
        response = (
            "示例关注标的（非投资建议，请自评风险）：\n"
            + "\n".join(lines)
            + "\n\n建议：分批建仓，单票不超过总仓 5%-10%，总仓位控制在 50% 以下。投资有风险，入市需谨慎。"
        )
        return {
            'success': True,
            'response': response,
            'intent': 'advice',
            'thinking': "Generic recommendation fallback (no ticker).",
        }

    def _handle_with_search(
        self,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理通用搜索查询或需要澄清的查询"""
        
        if not self.tools_module or not hasattr(self.tools_module, 'search'):
            return {
                'success': True, # 视为成功返回澄清信息
                'response': self._generate_clarification_response(query),
                'needs_clarification': True,
                'intent': 'chat',
                'thinking': "No ticker and no search tool, asked for clarification."
            }

        try:
            search_result = self.tools_module.search(query)

            if self.llm and LANGCHAIN_AVAILABLE:
                prompt = f"""You are a helpful financial assistant. Please answer the user's question based on the provided search results.

User Question: {query}
Search Results: {search_result[:3000]}

**CRITICAL REQUIREMENTS**:
1. Provide a concise and accurate answer based ONLY on the information in the search results.
2. If the search results do not contain an answer, state that you couldn't find the information.
3. Organize the information clearly.
4. Respond in Chinese.
"""
                response = self.llm.invoke([HumanMessage(content=prompt)])
                
                return {
                    'success': True,
                    'response': response.content,
                    'data': {'query_type': 'general_search', 'search_result': search_result[:500]},
                    'intent': 'general_search',
                    'used_search': True,
                    'thinking': "Used search tool and LLM for general query."
                }
            else:
                # 没有 LLM，直接返回搜索结果摘要
                return {
                    'success': True,
                    'response': f"根据搜索结果，关于 “{query}” 的信息如下：\n{search_result[:800]}...",
                    'data': {'query_type': 'general_search', 'search_result': search_result[:500]},
                    'intent': 'general_search',
                    'used_search': True,
                    'thinking': "Used search tool; no LLM for summary."
                }
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'response': f"搜索 “{query}” 时出错: {str(e)}",
                'error': str(e),
                'intent': 'chat',
                'thinking': f"General search failed: {str(e)}"
            }

    # --- 辅助方法 ---
    
    def _format_price_response(self, ticker: str, price_data: Any, source: str) -> str:
        """格式化价格响应"""
        if isinstance(price_data, str):
            response = price_data
            if source != 'cache':
                response += f"\n\n📊 数据来源: {source}"
            return response
        
        if isinstance(price_data, dict):
            # 假设 price_data 包含 price, change, change_percent 字段
            price = price_data.get('price', 'N/A')
            change = price_data.get('change', 0)
            change_pct = price_data.get('change_percent', 0)
            
            # 安全格式化
            try:
                price_str = f"${float(price):.2f}"
            except (ValueError, TypeError):
                price_str = str(price)

            try:
                change_str = f"{'+' if change >= 0 else ''}${float(change):.2f}"
                change_pct_str = f"{'+' if change_pct >= 0 else ''}{float(change_pct):.2f}%"
                
                emoji = "📈" if change >= 0 else "📉"
                # 假设需要换行符来保持格式化
                response = f"{emoji} {ticker} 当前价格: {price_str}\n变动: {change_str} ({change_pct_str})"
                
                # 添加数据来源，除非它是缓存数据
                if source != 'cache':
                    response += f"\n📊 数据来源: {source}"
                    
                return response
            except (ValueError, TypeError):
                 return f"💰 {ticker} 当前价格: {price_str}"

        return str(price_data)

    def _generate_clarification_response(self, query: str) -> str:
        """Generate clarification request"""
        responses = [
            "请问您想了解哪支股票？请提供股票代码（如 AAPL）或公司名称。",
            "我需要知道您问的是哪支股票。请告诉我股票代码或公司名称，例如 'AAPL' 或 '苹果'。",
            "您想查询哪支股票的信息？请提供股票代码或公司名称。",
        ]
        return random.choice(responses)
    
    # --- LLM 增强方法（保留，但通常 handle 方法已覆盖） ---

    def handle_with_llm(
        self, 
        query: str, 
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        使用 LLM 增强的处理方法，先获取数据，然后让 LLM 生成自然的回复
        """
        # 1. 首先获取基础数据
        basic_result = self.handle(query, metadata, context)
        
        # 行情类直接返回，避免 LLM 改写价格细节
        if basic_result.get('intent') in {'price'}:
            return basic_result
        
        if not basic_result.get('success') or not self.llm or not LANGCHAIN_AVAILABLE:
            return basic_result
        
        # 2. 使用 LLM 生成更自然的回复
        try:
            raw_response = basic_result.get('response', '')
            
            prompt = f"""你是财经助手，请基于以下“检索结果”用中文简洁回答用户。保持 2-5 句摘要，并保留所有可用链接，格式为 Markdown 可点击链接。

用户问题: {query}
检索结果:
{raw_response}

输出要求:
1) 先给 2-5 句摘要，包含关键日期、事件、影响。
2) 在摘要后追加“链接:”小节，逐条列出检索结果里出现的 URL，使用 Markdown 链接格式 `[来源或URL](URL)`，不丢失任何链接。
3) 如果没有找到有效链接，明确说明“暂无可用链接”。
4) 不要提到“检索结果/原文”等字样。
"""
            response = self.llm.invoke([HumanMessage(content=prompt)])
            
            # 合并 LLM 增强后的内容，保留原有数据和意图
            final_result = basic_result.copy()
            final_result['response'] = response.content
            final_result['enhanced_by_llm'] = True
            
            return final_result
        
        except Exception as e:
            traceback.print_exc()
            # LLM 增强失败，返回基础结果
            return basic_result
