# -*- coding: utf-8 -*-
"""
ChatHandler - 快速对话处理器
处理简单问题，提供快速简洁的回答

核心修复点:
1. 修复了 _handle_chat_query 的 AttributeError。
2. 移除了 _is_chat_query 中的重复逻辑。
3. 优化了 handle 方法中 query_lower 的定义，避免冗余。
"""

import logging
import sys
import os
import random
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


# 尝试导入 LangChain 核心模块（假设已安装）
try:
    from langchain_core.messages import HumanMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.info("[ChatHandler] Warning: langchain_core not found. LLM features disabled.")


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

    def __init__(self, llm=None, orchestrator=None, news_agent=None, price_agent=None):
        """
        初始化处理器

        Args:
            llm: LLM 实例 (例如 LangChain Runnable)
            orchestrator: ToolOrchestrator 实例
            news_agent: NewsAgent 实例 (P1: CHAT 意图也调用子 Agent)
            price_agent: PriceAgent 实例
        """
        self.llm = llm
        self.orchestrator = orchestrator
        self.news_agent = news_agent
        self.price_agent = price_agent
        self.tools_module = None
        self._init_tools()
    
    def _init_tools(self):
        """初始化工具函数"""
        # 优先从 orchestrator 获取 tools_module
        if self.orchestrator and hasattr(self.orchestrator, 'tools_module') and self.orchestrator.tools_module:
            self.tools_module = self.orchestrator.tools_module
            logger.info("[ChatHandler] 从 orchestrator 获取 tools 模块")
            return
        
        # 回退：直接导入
        try:
            # 假设 tools 模块在 backend.tools 包或项目根目录
            from backend import tools
            self.tools_module = tools
            logger.info("[ChatHandler] 成功从 backend.tools 导入")
        except ImportError:
            try:
                import tools
                self.tools_module = tools
                logger.info("[ChatHandler] 成功从 tools 导入")
            except ImportError as e:
                self.tools_module = None
                logger.info(f"[ChatHandler] 警告: 无法导入 tools 模块: {e}")
    
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
            # 1. 显式提取元数据中的 tickers (用户本次输入明确提到的)
            explicit_tickers = metadata.get('tickers', [])
            tickers = list(explicit_tickers)
            explicit_company = bool(metadata.get('company_names') or metadata.get('company_mentions'))
            company_hint = None
            if explicit_company:
                if metadata.get('company_names'):
                    company_hint = metadata.get('company_names')[0]
                elif metadata.get('company_mentions'):
                    company_hint = metadata.get('company_mentions')[0]
            resolution = None
            # P2: 只有在没有 ticker 且有 company_mentions 时才调用在线解析
            # 如果 Router 已经识别出 ticker（如 AAPL），就不要再调用在线解析
            if explicit_company and not tickers and metadata.get('company_mentions'):
                resolution = self._resolve_company_ticker(company_hint, context)
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
                        else:
                            metadata['ticker_candidates'] = matches

            # 2. 检查是否为泛化推荐 (无明确 ticker 且包含"推荐几只"等模式)
            #    注意：如果用户说 "推荐几只像 AAPL 的股票"，explicit_tickers 会有 AAPL，这时不算纯泛化。
            #    但如果用户只说 "推荐几只股票"，explicit_tickers 为空。
            is_generic_rec = self._is_generic_recommendation_intent(query_lower)
            is_price_query = self._is_price_query(query_lower)
            is_economic_events_query = self._is_economic_events_query(query_lower)
            is_news_sentiment_query = self._is_news_sentiment_query(query_lower)
            is_sentiment_query = self._is_sentiment_query(query_lower)
            is_news_query = self._is_news_query(query_lower)
            is_financial_report_query = self._is_financial_report_query(query_lower)  # P3: 财报查询

            # 3. 只有在非泛化推荐，且没有明确 ticker 时，才继承上下文
            #    修复：如果用户问"推荐几只股票"，不要把上下文的 AAPL 强行塞进来
            if not tickers and not is_generic_rec and not explicit_company:
                if context and hasattr(context, 'current_focus') and context.current_focus:
                    tickers = [context.current_focus]

            primary_ticker = tickers[0] if tickers else None

            if metadata.get('ticker_candidates') and not tickers:
                return self._handle_company_clarification(query, metadata, context)

            if is_economic_events_query:
                return self._handle_economic_events(query, context)

            if is_news_sentiment_query:
                return self._handle_news_sentiment_query(primary_ticker, query, context)

            if is_sentiment_query:
                return self._handle_sentiment_query(query, context, primary_ticker)

            # P3: 财报查询优先使用 FundamentalAgent
            if is_financial_report_query and primary_ticker:
                return self._handle_financial_report_query(primary_ticker, query, context)

            # 优先处理新闻意图：有 ticker 直接拉新闻；无 ticker 先用市场泛化新闻，再兜底默认指数
            if is_news_query:
                if primary_ticker:
                    return self._handle_news_query(primary_ticker, query, context)
                if explicit_company:
                    return self._handle_company_clarification(query, metadata, context)
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
                        logger.info(f"[ChatHandler] market news fallback failed: {e}")
                default_news_ticker = os.getenv("DEFAULT_NEWS_TICKER", "^GSPC")
                return self._handle_news_query(default_news_ticker, query, context)
            
            # 检查是否为对比查询
            if metadata.get('is_comparison') and len(tickers) >= 2:
                return self._handle_comparison_query(tickers, query, metadata, context)

            # 如果没有股票代码，尝试从上下文获取 (上面已经处理过继承逻辑，这里只需判断最终 tickers)

            if not tickers:
                logger.info(f"[ChatHandler] 检查闲聊/建议意图: Query='{query_lower}'")

                # 新闻类无 ticker 查询：默认用大盘指数
                if is_price_query:
                    if explicit_company:
                        return self._handle_company_clarification(query, metadata, context)
                    return self._handle_price_clarification(query, context)

                if is_news_query:
                    if explicit_company:
                        return self._handle_company_clarification(query, metadata, context)
                    default_news_ticker = os.getenv("DEFAULT_NEWS_TICKER", "^GSPC")
                    return self._handle_news_query(default_news_ticker, query, context)

                # 泛化建议查询 (命中"推荐几只"等)
                if is_generic_rec or self._is_advice_query(query_lower):
                    logger.info("[ChatHandler] ✅ 命中泛化建议意图（无 ticker）")
                    return self._handle_generic_recommendation(query)

                if self._is_chat_query(query_lower):
                    logger.info("[ChatHandler] 🚀 意图命中: 闲聊/问候。")
                    return self._handle_chat_query(query)

                logger.info("[ChatHandler] ⚠️ 意图未命中: 闲聊。回退到通用搜索。")
                return self._handle_with_search(query, context)

            # 获取第一个股票的信息 (如果 tickers 有内容)
            ticker = primary_ticker or (tickers[0] if tickers else None)

            # 判断查询类型并获取相应数据
            if self._is_composition_query(query_lower):
                # 成分股/持仓查询
                return self._handle_composition_query(ticker, query, context)
            elif is_price_query:
                return self._handle_price_query(ticker, query, context)
            elif is_news_query:
                return self._handle_news_query(ticker, query, context)
            elif self._is_advice_query(query_lower):
                # 投资建议查询
                return self._handle_advice_query(ticker, query, context)
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
    
    def handle_schema_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Handle schema-selected tool calls without heuristic intent detection."""
        tool = (tool_name or "").strip()
        args = args or {}
        ticker = args.get("ticker")
        tickers = args.get("tickers") if isinstance(args.get("tickers"), list) else []
        limit = args.get("limit")
        timeframe = args.get("timeframe")
        search_query = args.get("query") or query

        if tool == "get_price":
            result = self._handle_price_query(ticker, query, context)
        elif tool == "get_news":
            result = self._handle_news_query(ticker, query, context, limit=limit)
        elif tool == "compare_stocks":
            metadata = {"tickers": tickers, "is_comparison": True}
            result = self._handle_comparison_query(tickers, query, metadata, context)
        elif tool == "get_market_sentiment":
            result = self._handle_sentiment_query(query, context, ticker)
        elif tool == "get_economic_events":
            result = self._handle_economic_events(query, context)
        elif tool == "get_news_sentiment":
            result = self._handle_news_sentiment_query(ticker, query, context, limit=limit)
        elif tool == "search":
            result = self._handle_with_search(search_query, context)
        elif tool == "greeting":
            result = self._handle_chat_query(query)
        else:
            result = self._handle_with_search(search_query, context)

        if isinstance(result, dict):
            result.setdefault("method", "schema_router")
            if limit is not None:
                data = result.get("data") or {}
                data["limit"] = limit
                result["data"] = data
            if timeframe is not None:
                data = result.get("data") or {}
                data["timeframe"] = timeframe
                result["data"] = data
        return result

    def _is_generic_recommendation_intent(self, query: str) -> bool:
        """
        判断是否为泛化推荐意图 (不针对特定股票)
        例如: "推荐几只股票", "有什么好的投资机会", "最近买什么好"
        """
        patterns = [
            '推荐几只', '推荐股票', '什么股票', '买什么', '哪些股票',
            '投资机会', '值得买', '推荐一下', '有什么好', 'recommend some'
        ]
        return any(p in query for p in patterns)

    def _is_price_query(self, query: str) -> bool:
        keywords = ['价格', '股价', '多少钱', '现价', '市价', '报价', 'price', 'how much', '涨', '跌', '行情', '走势', '表现']
        return any(kw in query for kw in keywords)
    
    def _is_news_query(self, query: str) -> bool:
        news_keywords = ['新闻', '消息', 'news', '头条', 'headline', '热点', '快讯', '事件', '舆情', '公告']
        temporal_only = ['最新', '最近', '近几天', '这几天', '本周', '今天', '近一周']

        if any(kw in query for kw in news_keywords):
            return True

        if any(kw in query for kw in temporal_only):
            return not self._is_price_query(query)

        return False

    def _is_sentiment_query(self, query: str) -> bool:
        sentiment_strong = [
            '恐惧贪婪', '恐惧', '贪婪', '恐慌', 'fear & greed', 'fear and greed',
            'fear&greed', '情绪指标', '风险偏好', 'risk appetite'
        ]
        sentiment_soft = ['情绪', 'sentiment']
        market_context = ['市场', '股市', '美股', '大盘', '指数', '投资者', 'market', 'index', 'equity']

        if any(kw in query for kw in sentiment_strong):
            return True

        if any(kw in query for kw in sentiment_soft) and any(ctx in query for ctx in market_context):
            return True

        return False

    def _is_economic_events_query(self, query: str) -> bool:
        keywords = [
            '经济日历', '宏观日历', '经济事件', '宏观事件', '经济数据', '数据公布',
            '非农', 'cpi', 'ppi', 'gdp', 'pmi', 'fomc', '利率决议', '央行会议',
            'economic calendar', 'economic events', 'macro events', 'macro calendar'
        ]
        if any(kw in query for kw in keywords):
            return True
        if '日历' in query and '经济' in query:
            return True
        return False

    def _is_news_sentiment_query(self, query: str) -> bool:
        keywords = [
            '新闻情绪', '舆情', '舆情指数', '媒体情绪', 'news sentiment',
            'headline sentiment', 'sentiment of news', 'media sentiment'
        ]
        if any(kw in query for kw in keywords):
            return True
        if '情绪' in query and any(kw in query for kw in ['新闻', '快讯', 'headline', 'news']):
            return True
        return False
    
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

    def _is_financial_report_query(self, query: str) -> bool:
        """P3: 检测是否为财报/基本面查询"""
        keywords = [
            '财报', '财务', '年报', '季报', '业绩', '营收', '利润', '毛利', '净利',
            '收入', '支出', '现金流', '资产负债', '利润表', '损益表',
            'earnings', 'revenue', 'profit', 'income', 'financial', 'quarterly',
            'annual report', 'balance sheet', 'cash flow', 'eps', 'pe', 'roe', 'roa',
            '市盈率', '市净率', '净资产收益率', '每股收益', '估值'
        ]
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
    
    def _resolve_company_ticker(self, company_hint: Optional[str], context: Optional[Any]) -> Optional[Dict[str, Any]]:
        if not company_hint:
            return None
        if not self.tools_module or not hasattr(self.tools_module, 'resolve_company_ticker'):
            return None
        cache_key = f"ticker_lookup:{company_hint.lower()}"
        if context and hasattr(context, 'get_cached_data'):
            cached = context.get_cached_data(cache_key, max_age_seconds=86400)
            if cached:
                return cached
        try:
            result = self.tools_module.resolve_company_ticker(company_hint)
            if context and hasattr(context, 'cache_data'):
                context.cache_data(cache_key, result)
            return result
        except Exception as e:
            logger.info(f"[ChatHandler] ticker lookup failed for {company_hint}: {e}")
            return None

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

    def _handle_chat_query(self, query: str) -> Dict[str, Any]:
        """
        处理简单的闲聊和问候（例如：你好，你是谁，谢谢）。
        """
        if any(kw in query for kw in ['你好', '您好', '喂', '嗨', 'hello', 'hi']):
            response = "你好！我是一个金融智能分析助手，可以帮您查询股票价格、分析走势或生成深度报告。"
        elif any(kw in query for kw in ['你是谁', '你叫什么', '介绍自己', '自我介绍']):
            response = "我叫 FinSight Agent，是专为金融市场设计的人工智能。我可以实时获取数据，并解读复杂的市场信息。"
        elif any(kw in query for kw in ['谢谢', '再见', '好的', 'ok', 'bye']):
            response = "不客气，很高兴为您服务！如果您还有其他金融问题，随时可以问我。再见！"
        else:
            response = "很高兴与您交流！如需查询，请直接输入股票代码或公司名称。"

        return {
            'success': True,
            'response': response,
            'intent_detail': 'greeting_chat',
            'metadata': {},
        }
        
    def _handle_price_clarification(self, query: str, context: Optional[Any] = None) -> Dict[str, Any]:
        """Fallback when schema router should have asked for details."""
        return self._handle_with_search(query, context)

    def _handle_company_clarification(
        self,
        query: str,
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Fallback when schema router should have asked for details."""
        return self._handle_with_search(query, context)

    def _handle_price_query(
        self, 
        ticker: str, 
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """处理价格查询"""
        if not ticker:
            return self._handle_price_clarification(query, context)

        orchestrator_error = None
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
                    orchestrator_error = result.error
            except Exception as e:
                traceback.print_exc()
                orchestrator_error = str(e)
                logger.info(f"[ChatHandler] Orchestrator price fetch failed: {e}")
        
        # 回退到直接调用 tools
        if self.tools_module and hasattr(self.tools_module, 'get_stock_price'):
            try:
                # 假设 get_stock_price 返回字符串或字典
                price_info = self.tools_module.get_stock_price(ticker)
                if isinstance(price_info, str) and price_info.lower().startswith("error"):
                    raise ValueError(price_info)
                return {
                    'success': True,
                    'response': price_info,
                    'data': {'ticker': ticker, 'raw_price': price_info},
                    'intent': 'market_data',
                    'thinking': "Fetched price via direct tools module."
                }
            except Exception as e:
                traceback.print_exc()
                fallback = self._fallback_price_from_kline(ticker)
                if fallback:
                    return fallback

                error_msg = str(e)
                if orchestrator_error:
                    error_msg = f"{orchestrator_error}; {error_msg}"
                return {
                    'success': False,
                    'response': f"获取 {ticker} 价格时出错: {error_msg}",
                    'error': error_msg,
                    'intent': 'chat',
                    'thinking': f"Direct tool call for price failed: {error_msg}"
                }
        
        fallback = self._fallback_price_from_kline(ticker)
        if fallback:
            return fallback

        return {
            'success': False,
            'response': "价格查询工具暂不可用，请检查后端配置。",
            'error': 'tool_not_available',
            'intent': 'chat',
            'thinking': "No price fetching tool available."
        }
    
    def _fallback_price_from_kline(self, ticker: str) -> Optional[Dict[str, Any]]:
        """价格兜底：从 K 线数据取最近收盘价。"""
        if not self.tools_module or not hasattr(self.tools_module, 'get_stock_historical_data'):
            return None

        try:
            kline = self.tools_module.get_stock_historical_data(ticker, period="5d", interval="1d")
            data = kline.get("kline_data") if isinstance(kline, dict) else None
            if not data:
                return None
            last = data[-1]
            close_price = last.get("close")
            if close_price is None:
                return None
            date_label = last.get("time", "recent")
            response = f"{ticker} 最近收盘价: ${float(close_price):.2f} (日期: {date_label})"
            return {
                'success': True,
                'response': response,
                'data': {'ticker': ticker, 'raw_kline': last, 'source': 'kline'},
                'intent': 'market_data',
                'thinking': "Price fallback to kline data.",
            }
        except Exception as e:
            logger.info(f"[ChatHandler] Kline fallback failed for {ticker}: {e}")
            return None

    def _handle_news_query(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """处理新闻查询 - P1: 优先使用 NewsAgent 的反思循环"""
        cache_key = f"deepsearch:news:{ticker}"

        # 先查 KV 缓存
        if self.orchestrator and getattr(self.orchestrator, "cache", None):
            cached = self.orchestrator.cache.get(cache_key)
            if cached:
                text = cached.get("text") if isinstance(cached, dict) else str(cached)
                return {
                    'success': True,
                    'response': text,
                    'data': {'ticker': ticker, 'raw_news': text, 'cached': True, 'as_of': cached.get('as_of') if isinstance(cached, dict) else None},
                    'intent': 'company_news',
                    'thinking': "News served from KV cache.",
                }

        # P1: 优先使用 NewsAgent（带反思循环）
        if self.news_agent:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        agent_output = pool.submit(
                            asyncio.run, self.news_agent.research(query, ticker)
                        ).result(timeout=30)
                else:
                    agent_output = asyncio.run(self.news_agent.research(query, ticker))

                if agent_output and agent_output.summary:
                    # 缓存结果
                    if self.orchestrator and getattr(self.orchestrator, "cache", None):
                        self.orchestrator.cache.set(cache_key, {
                            "text": agent_output.summary,
                            "as_of": agent_output.as_of
                        }, data_type='news')
                    return {
                        'success': True,
                        'response': agent_output.summary,
                        'data': {
                            'ticker': ticker,
                            'raw_news': agent_output.summary,
                            'evidence': [e.__dict__ for e in agent_output.evidence] if agent_output.evidence else [],
                            'confidence': agent_output.confidence,
                            'data_sources': agent_output.data_sources,
                            'as_of': agent_output.as_of
                        },
                        'intent': 'company_news',
                        'thinking': f"NewsAgent research completed with {len(agent_output.evidence)} evidence items.",
                    }
            except Exception as e:
                logger.info(f"[ChatHandler] NewsAgent failed for {ticker}: {e}")

        # 尝试 DeepSearch 聚合（高召回，含链接）
        if self.tools_module and hasattr(self.tools_module, 'deepsearch_news'):
            try:
                ds_result = self.tools_module.deepsearch_news(ticker)
                text = ds_result.get("text", "")
                if self.orchestrator and getattr(self.orchestrator, "cache", None):
                    self.orchestrator.cache.set(cache_key, ds_result, data_type='news')
                if context and hasattr(context, 'cache_data'):
                    context.cache_data(f'news:{ticker}', ds_result)
                return {
                    'success': True,
                    'response': text,
                    'data': {'ticker': ticker, 'raw_news': ds_result, 'source': ds_result.get('source'), 'as_of': ds_result.get('as_of')},
                    'intent': 'company_news',
                    'thinking': "Fetched news via DeepSearch aggregation.",
                }
            except Exception as e:
                logger.info(f"[ChatHandler] DeepSearch news failed for {ticker}: {e}")

        # 回退常规新闻工具
        if self.tools_module and hasattr(self.tools_module, 'get_company_news'):
            try:
                if limit is not None:
                    news_info = self.tools_module.get_company_news(ticker, limit=limit)
                else:
                    news_info = self.tools_module.get_company_news(ticker)
                news_response = news_info
                if isinstance(news_info, list):
                    if limit is not None:
                        news_info = news_info[: max(1, int(limit))]
                    formatter = getattr(self.tools_module, "format_news_items", None)
                    if formatter:
                        news_response = formatter(news_info, title=f"Latest News ({ticker})")
                    else:
                        news_response = "\n".join(
                            f"- {(item.get('headline') or item.get('title') or 'No title')}"
                            for item in news_info
                            if isinstance(item, dict)
                        )
                
                if context and hasattr(context, 'cache_data'):
                    context.cache_data(f'news:{ticker}', news_info)
                
                return {
                    'success': True,
                    'response': news_response,
                    'data': {'ticker': ticker, 'raw_news': news_info},
                    'intent': 'company_news',
                    'thinking': "Fetched company news via tools module.",
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

    def _handle_financial_report_query(
        self,
        ticker: str,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """P3: 处理财报/基本面查询 - 使用 FundamentalAgent + DeepSearch"""
        cache_key = f"fundamental:{ticker}"

        # 先查 KV 缓存
        if self.orchestrator and getattr(self.orchestrator, "cache", None):
            cached = self.orchestrator.cache.get(cache_key)
            if cached:
                return {
                    'success': True,
                    'response': cached.get("text", str(cached)),
                    'data': {'ticker': ticker, 'cached': True, 'as_of': cached.get('as_of')},
                    'intent': 'financial_report',
                    'thinking': "Financial data served from KV cache.",
                }

        # 尝试使用工具获取财务数据
        if self.tools_module:
            try:
                financials = {}
                company_info = ""

                if hasattr(self.tools_module, 'get_financial_statements'):
                    financials = self.tools_module.get_financial_statements(ticker)
                if hasattr(self.tools_module, 'get_company_info'):
                    company_info = self.tools_module.get_company_info(ticker)

                # 格式化响应
                response_parts = []
                if company_info:
                    response_parts.append(f"**{ticker} 公司概况**\n{company_info[:500]}...")

                if financials and not financials.get('error'):
                    response_parts.append(f"\n**财务数据**")
                    if financials.get('income_statement'):
                        response_parts.append("- 利润表数据已获取")
                    if financials.get('balance_sheet'):
                        response_parts.append("- 资产负债表数据已获取")
                    if financials.get('cash_flow'):
                        response_parts.append("- 现金流量表数据已获取")

                response = "\n".join(response_parts) if response_parts else f"已获取 {ticker} 的财务数据"

                # 缓存结果
                if self.orchestrator and getattr(self.orchestrator, "cache", None):
                    self.orchestrator.cache.set(cache_key, {
                        "text": response,
                        "financials": financials,
                        "company_info": company_info,
                    }, data_type='fundamental')

                return {
                    'success': True,
                    'response': response,
                    'data': {
                        'ticker': ticker,
                        'financials': financials,
                        'company_info': company_info,
                    },
                    'intent': 'financial_report',
                    'thinking': f"Fetched financial data for {ticker} via tools module.",
                }
            except Exception as e:
                logger.info(f"[ChatHandler] Financial report query failed for {ticker}: {e}")

        return {
            'success': False,
            'response': f"获取 {ticker} 财务数据时出错，请稍后重试。",
            'error': 'tool_error',
            'intent': 'financial_report',
            'thinking': "Financial data fetch failed."
        }

    def _handle_sentiment_query(
        self,
        query: str,
        context: Optional[Any] = None,
        ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        orchestrator_error = None
        if self.orchestrator and hasattr(self.orchestrator, 'fetch'):
            try:
                result = self.orchestrator.fetch('sentiment', 'market')
                if result and result.success:
                    sentiment_text = result.data
                    response = self._format_sentiment_response(sentiment_text, query, ticker)
                    return {
                        'success': True,
                        'response': response,
                        'data': {
                            'raw_sentiment': sentiment_text,
                            'source': result.source,
                            'cached': result.cached,
                            'as_of': result.as_of,
                            'tried_sources': getattr(result, 'tried_sources', []),
                        },
                        'intent': 'market_sentiment',
                        'thinking': "Fetched market sentiment via Orchestrator.",
                    }
                if result:
                    orchestrator_error = result.error
            except Exception as e:
                orchestrator_error = str(e)
                logger.info(f"[ChatHandler] Orchestrator sentiment fetch failed: {e}")

        if self.tools_module and hasattr(self.tools_module, 'get_market_sentiment'):
            try:
                sentiment_text = self.tools_module.get_market_sentiment()
                response = self._format_sentiment_response(sentiment_text, query, ticker)
                if context and hasattr(context, 'cache_data'):
                    context.cache_data('sentiment:market', sentiment_text)
                return {
                    'success': True,
                    'response': response,
                    'data': {'raw_sentiment': sentiment_text, 'source': 'tools_module'},
                    'intent': 'market_sentiment',
                    'thinking': "Fetched market sentiment via tools module.",
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取市场情绪指标失败: {str(e)}",
                    'error': str(e),
                    'intent': 'market_sentiment',
                    'thinking': f"Tool call for sentiment failed: {str(e)}",
                }

        response = "市场情绪指标暂不可用，如需我改为整理市场要闻请告诉我。"
        if orchestrator_error:
            response = f"{response} (原因: {orchestrator_error})"
        return {
            'success': False,
            'response': response,
            'error': 'tool_not_available',
            'intent': 'market_sentiment',
            'thinking': "No sentiment tool available.",
        }

    def _format_sentiment_response(
        self,
        sentiment_text: Any,
        query: str,
        ticker: Optional[str]
    ) -> str:
        base_text = str(sentiment_text)
        query_lower = query.lower()
        notes = []
        if ticker:
            notes.append(f"说明: 这是整体市场情绪，不是 {ticker} 的单票情绪。")
        if '分布' in query or 'distribution' in query_lower:
            notes.append("如果需要分布或历史走势，请告诉我维度或时间范围。")
        if notes:
            return f"{base_text}\n" + " ".join(notes)
        return base_text

    def _handle_economic_events(
        self,
        query: str,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        orchestrator_error = None
        if self.orchestrator and hasattr(self.orchestrator, 'fetch'):
            try:
                result = self.orchestrator.fetch('economic_events', 'macro')
                if result and result.success:
                    text = str(result.data)
                    return {
                        'success': True,
                        'response': text,
                        'data': {
                            'raw_events': result.data,
                            'source': result.source,
                            'cached': result.cached,
                            'as_of': result.as_of,
                            'tried_sources': getattr(result, 'tried_sources', []),
                        },
                        'intent': 'economic_events',
                        'thinking': "Fetched economic events via Orchestrator.",
                    }
                if result:
                    orchestrator_error = result.error
            except Exception as e:
                orchestrator_error = str(e)
                logger.info(f"[ChatHandler] Orchestrator economic events fetch failed: {e}")

        if self.tools_module and hasattr(self.tools_module, 'get_economic_events'):
            try:
                text = self.tools_module.get_economic_events()
                if context and hasattr(context, 'cache_data'):
                    context.cache_data('economic_events', text)
                return {
                    'success': True,
                    'response': text,
                    'data': {'raw_events': text, 'source': 'tools_module'},
                    'intent': 'economic_events',
                    'thinking': "Fetched economic events via tools module.",
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取经济日历失败: {str(e)}",
                    'error': str(e),
                    'intent': 'economic_events',
                    'thinking': f"Tool call for economic events failed: {str(e)}",
                }

        response = "经济日历暂不可用，请稍后重试。"
        if orchestrator_error:
            response = f"{response} (原因: {orchestrator_error})"
        return {
            'success': False,
            'response': response,
            'error': 'tool_not_available',
            'intent': 'economic_events',
            'thinking': "No economic events tool available.",
        }

    def _handle_news_sentiment_query(
        self,
        ticker: Optional[str],
        query: str,
        context: Optional[Any] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        if not ticker:
            return self._handle_with_search(query, context)

        orchestrator_error = None
        if limit is None and self.orchestrator and hasattr(self.orchestrator, 'fetch'):
            try:
                result = self.orchestrator.fetch('news_sentiment', ticker)
                if result and result.success:
                    text = str(result.data)
                    return {
                        'success': True,
                        'response': text,
                        'data': {
                            'ticker': ticker,
                            'raw_sentiment': result.data,
                            'source': result.source,
                            'cached': result.cached,
                            'as_of': result.as_of,
                            'tried_sources': getattr(result, 'tried_sources', []),
                        },
                        'intent': 'news_sentiment',
                        'thinking': "Fetched news sentiment via Orchestrator.",
                    }
                if result:
                    orchestrator_error = result.error
            except Exception as e:
                orchestrator_error = str(e)
                logger.info(f"[ChatHandler] Orchestrator news sentiment fetch failed: {e}")

        if self.tools_module and hasattr(self.tools_module, 'get_news_sentiment'):
            try:
                if limit is not None:
                    text = self.tools_module.get_news_sentiment(ticker, limit=limit)
                else:
                    text = self.tools_module.get_news_sentiment(ticker)
                if context and hasattr(context, 'cache_data'):
                    context.cache_data(f'news_sentiment:{ticker}', text)
                return {
                    'success': True,
                    'response': text,
                    'data': {'ticker': ticker, 'raw_sentiment': text, 'source': 'tools_module'},
                    'intent': 'news_sentiment',
                    'thinking': "Fetched news sentiment via tools module.",
                }
            except Exception as e:
                traceback.print_exc()
                return {
                    'success': False,
                    'response': f"获取 {ticker} 新闻情绪失败: {str(e)}",
                    'error': str(e),
                    'intent': 'news_sentiment',
                    'thinking': f"Tool call for news sentiment failed: {str(e)}",
                }

        response = "新闻情绪工具暂不可用，请稍后重试。"
        if orchestrator_error:
            response = f"{response} (原因: {orchestrator_error})"
        return {
            'success': False,
            'response': response,
            'error': 'tool_not_available',
            'intent': 'news_sentiment',
            'thinking': "No news sentiment tool available.",
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
                'response': 'Search tool unavailable. Please try again later.',
                'error': 'search_unavailable',
                'intent': 'general_search',
                'thinking': 'Search tool unavailable for fallback.'
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
                prompt = f"""<role>专业金融分析师 — 指数/基金成分股专家</role>

<task>基于搜索结果，整理 {ticker} 的完整成分股/持仓列表。</task>

<input>
用户问题: {query}
搜索结果: {search_result[:3000]}
</input>

<requirements>
1. 提取搜索结果中提到的每一个成分股/持仓
2. 每个成分列出：公司全称（如"苹果公司"）、股票代码（如 AAPL）、权重占比（如有）
3. 按权重从高到低排列，使用清晰的编号或要点格式
4. 提供完整列表，不要只给摘要
5. 搜索结果中未提及的信息不要编造
</requirements>

<constraints>
- 使用简体中文输出
- 禁止开场白，直接输出列表
- 权重数据缺失时标注"权重未披露"
</constraints>
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
                prompt = f"""<role>专业金融分析师 — 对比分析专家</role>

<task>对比分析 {ticker1} 和 {ticker2}，为用户提供有决策价值的差异解读。</task>

<input>
用户问题: {query}
{context_info}
</input>

<analysis_framework>
1. **核心差异**: 投资标的类型、行业分布、风险特征
2. **投资特性**: 适合的投资者类型、持有策略、预期收益/风险比
3. **关键数据对比**: 近期表现、估值水平、波动率（基于已有数据）
4. **适用场景**: 什么情况下选 A，什么情况下选 B
</analysis_framework>

<constraints>
- 使用简体中文，专业但易懂
- 基于已有数据分析，数据不足时坦诚说明
- 禁止开场白，直接输出对比分析
</constraints>
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
                logger.info(f"[ChatHandler] LLM comparison analysis failed: {e}")
        
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
            prompt = f"""<role>专业金融投资顾问</role>

<task>基于用户问题和已有数据，为 {ticker} 提供具体、可操作的投资建议。</task>

<input>
用户问题: {query}
{context_info}
</input>

<requirements>
1. 判断用户意图（已持仓 vs 准备入场），针对性建议
2. 提供具体可执行的操作建议（如"建议分 3-5 批建仓"、"持有观望"）
3. 附 2-3 句简明市场分析，引用具体数据点
4. 末尾包含风险提示
</requirements>

<constraints>
- 使用简体中文，友好专业的语气
- 禁止开场白，直接输出建议
- 建议必须具体，避免"建议关注"等模糊表述
- 末尾必须附加以下文字:

⚠️ **AI生成建议提示**：以上建议由AI生成，仅供参考，不构成投资建议。投资有风险，请根据自身情况谨慎决策。
</constraints>
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
                'success': False,
                'response': 'Search tool unavailable. Please try again later.',
                'error': 'search_unavailable',
                'intent': 'general_search',
                'thinking': 'Search tool unavailable for fallback.'
            }

        try:
            search_result = self.tools_module.search(query)

            if self.llm and LANGCHAIN_AVAILABLE:
                prompt = f"""<role>金融信息助手</role>

<task>基于搜索结果，准确回答用户的金融相关问题。</task>

<input>
用户问题: {query}
搜索结果: {search_result[:3000]}
</input>

<requirements>
1. 仅基于搜索结果中的信息作答，不编造
2. 搜索结果无法回答时，坦诚说明"未找到相关信息"
3. 信息组织清晰，按逻辑分点
4. 优先提取关键数据点和结论
</requirements>

<constraints>
- 使用简体中文
- 禁止开场白，直接输出答案
- 简洁有力，避免冗余
</constraints>
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

    # --- LLM 增强方法（保留，但通常 handle 方法已覆盖） ---
    def _build_llm_enhance_prompt(self, query: str, raw_response: str) -> str:
        """Build the prompt used for LLM-enhanced chat responses."""
        return f"""<role>专业金融助手</role>

<task>基于以下数据，用简体中文简洁回答用户问题。</task>

<input>
用户问题: {query}
数据:
{raw_response}
</input>

<requirements>
1) 直接回答，2-4 句话，突出关键数字和时间节点
2) 禁止使用"根据数据"、"根据检索结果"等元表述
3) 数据中含 URL 链接时，在末尾用 markdown 格式列出参考链接；无链接则不提
4) 语气专业友好，如同资深分析师面对面解答
5) 禁止开场白
</requirements>
"""

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
        if basic_result.get('intent') in {'price', 'market_news', 'company_news', 'market_sentiment', 'economic_events', 'news_sentiment'} or basic_result.get('needs_clarification'):
            return basic_result
        
        if not basic_result.get('success') or not self.llm or not LANGCHAIN_AVAILABLE:
            return basic_result
        
        # 2. 使用 LLM 生成更自然的回复
        try:
            raw_response = basic_result.get('response', '')

            prompt = self._build_llm_enhance_prompt(query, raw_response)
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

    async def stream_with_llm(
        self,
        query: str,
        metadata: Dict[str, Any],
        context: Optional[Any],
        result_container: Dict[str, Any]
    ):
        """Stream the LLM-enhanced response token by token."""
        # 1. 先获取基础数据
        basic_result = self.handle(query, metadata, context)

        # 行情类直接返回，避免 LLM 改写价格细节
        if basic_result.get('intent') in {'price', 'market_news', 'company_news', 'market_sentiment', 'economic_events', 'news_sentiment'} or basic_result.get('needs_clarification'):
            result_container.update(basic_result)
            response_text = basic_result.get('response', '')
            if response_text:
                yield response_text
            return

        if not basic_result.get('success') or not self.llm or not LANGCHAIN_AVAILABLE:
            result_container.update(basic_result)
            response_text = basic_result.get('response', '')
            if response_text:
                yield response_text
            return

        raw_response = basic_result.get('response', '')
        prompt = self._build_llm_enhance_prompt(query, raw_response)

        full_response = ""
        try:
            if hasattr(self.llm, 'astream'):
                async for chunk in self.llm.astream([HumanMessage(content=prompt)]):
                    token = getattr(chunk, 'content', '')
                    if token:
                        full_response += token
                        yield token
            else:
                response = self.llm.invoke([HumanMessage(content=prompt)])
                full_response = getattr(response, 'content', '') or ''
                if full_response:
                    yield full_response

            final_result = basic_result.copy()
            final_result['response'] = full_response or raw_response
            if full_response:
                final_result['enhanced_by_llm'] = True
            result_container.update(final_result)
        except Exception:
            traceback.print_exc()
            result_container.update(basic_result)
            if raw_response:
                yield raw_response
