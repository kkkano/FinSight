# -*- coding: utf-8 -*-
"""
ConversationRouter - Conversation Router
Handles intent recognition and mode dispatch
"""

import logging
from enum import Enum
from typing import Tuple, Dict, Any, Optional, List, Callable
import re

logger = logging.getLogger(__name__)


# Import shared ticker mapping
from backend.config.ticker_mapping import (
    COMPANY_MAP,
    CN_TO_TICKER,
    INDEX_ALIASES,
    KNOWN_TICKERS,
    COMMON_WORDS,
    extract_tickers,
)

try:
    from .context import ContextManager
except ImportError:
    class ContextManager:
        def get_context_summary(self) -> str:
            return "No conversation history"
        def update_context(self, intent: Enum, metadata: Dict[str, Any]):
            pass


class Intent(Enum):
    """Intent types"""
    CHAT = "chat"          # Quick Q&A (financial data)
    REPORT = "report"      # Deep analysis report
    ALERT = "alert"        # Monitoring subscription
    ECONOMIC_EVENTS = "economic_events"  # Economic calendar/macro events
    NEWS_SENTIMENT = "news_sentiment"    # News sentiment
    CLARIFY = "clarify"    # Needs clarification
    FOLLOWUP = "followup"  # Follow-up question
    GREETING = "greeting"  # Greeting/small talk


class ConversationRouter:
    """
    Conversation Router

    Features:
    - Intent recognition (rule + LLM hybrid)
    - Metadata extraction (ticker, company name)
    - Route to corresponding handler
    """

    def __init__(self, llm=None):
        """
        Initialize router

        Args:
            llm: LLM instance for complex intent classification (optional)
        """
        self.llm = llm
        self._handlers: Dict[Intent, Callable] = {}

    def register_handler(self, intent: Intent, handler: Callable) -> None:
        """Register intent handler"""
        self._handlers[intent] = handler
    
    def route(self, query: str, context: ContextManager) -> Tuple[Intent, Dict[str, Any], Optional[Callable]]:
        """
        核心路由方法：
        1. 调用 classify_intent 识别意图和提取元数据。
        2. 根据意图找到对应的处理器。
        
        Args:
            query: 用户查询
            context: ContextManager 实例，用于获取上下文信息
            
        Returns:
            (Intent, metadata, handler) - 意图、元数据和对应的处理函数
        """
        # 1. 获取上下文摘要 (用于 FOLLOWUP/CHAT 的意图判断)
        context_summary = context.get_summary()
        last_long = context.get_last_long_response()

        # 2. 识别意图和提取元数据
        intent, metadata = self.classify_intent(query, context_summary, last_long)
        
        # 3. 找到对应的处理器
        handler = self._handlers.get(intent)
        
        return intent, metadata, handler

    def classify_intent(self, query: str, context_summary: str = "", last_long_response: Optional[str] = None) -> Tuple[Intent, Dict[str, Any]]:
        """
        分类用户意图
        
        Args:
            query: 用户查询
            context_summary: 对话历史摘要
            
        Returns:
            (Intent, metadata) - 意图类型和提取的元数据
        """
        # 1. 提取元数据
        metadata = self._extract_metadata(query)
        if last_long_response:
            metadata["last_long_response"] = last_long_response
        
        # 2. 规则快速匹配 (优先处理闲聊/问候，避免浪费 LLM Token 或被误判)
        quick_intent = self._quick_match(query, context_summary, last_long_response, metadata)
        if quick_intent and quick_intent != Intent.CLARIFY:
            return quick_intent, metadata

        # 3. LLM 兜底：仅在需要澄清且包含金融上下文时尝试提升意图判断
        if self.llm:
            should_try_llm = (
                quick_intent is None
                or (
                    quick_intent == Intent.CLARIFY
                    and (
                        self._contains_financial_keywords(query)
                        or bool(metadata.get('tickers'))
                        or bool(metadata.get('company_names'))
                        or bool(metadata.get('company_mentions'))
                    )
                )
            )
            if should_try_llm:
                if quick_intent is None:
                    fallback_reason = "no_rule_match"
                else:
                    fallback_reason = "clarify_with_financial_context"
                logger.info(
                    "[Router] LLM fallback start"
                    f" reason={fallback_reason}"
                    f" query={query!r}"
                    f" tickers={metadata.get('tickers', [])}"
                    f" company_names={metadata.get('company_names', [])}"
                )
                try:
                    llm_intent = self._llm_classify(query, context_summary, metadata)
                    logger.info(
                        "[Router] LLM fallback result"
                        f" reason={fallback_reason}"
                        f" intent={llm_intent.value}"
                        f" query={query!r}"
                    )
                    return llm_intent, metadata
                except Exception as e:
                    logger.info(f"[Router] LLM 意图识别失败: {e}，回退到规则匹配")

        if quick_intent:
            return quick_intent, metadata

        # 4. 根据是否有股票代码决定默认意图
        if metadata.get('tickers'):
            # 有股票代码但没有明确意图关键词，默认为快速查询
            return Intent.CHAT, metadata
        
        # 5. 默认回退：既没有 ticker，也没有匹配到规则 -> CLARIFY
        return Intent.CLARIFY, metadata
    
    def _quick_match(
        self,
        query: str,
        context_summary: str = "",
        last_long_response: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Intent]:
        """
        规则快速匹配
        """
        metadata = metadata or {}
        query_lower = query.lower().strip()
        
        # === 1. 问候/闲聊 (最高优先级) ===
        greeting_keywords = [
            '自我介绍', '你是谁', '你是做什么的', 
            'introduce yourself', 'who are you', 'what can you do',
            '早上好', '晚上好'
        ]
        
        # 强制将最简单的问候语直接匹配为 GREETING
        is_simple_greeting = any(kw == query_lower for kw in ['你好', '您好', 'hi', 'hello', '喂'])
        has_greeting_kw = any(kw in query_lower for kw in greeting_keywords)
        
        if is_simple_greeting or has_greeting_kw:
            # 只有当查询不包含明显的金融意图时，才视为纯问候
            if not self._contains_financial_keywords(query_lower):
                return Intent.GREETING

        # === 2. 报告关键词（只有明确要求深度报告时才触发）===
        # 注意：单独的"分析"太宽泛，移除它，只保留明确要求深度报告的关键词
        report_keywords = [
            '详细分析', '深度分析', '全面分析', '投资分析', '深入分析',
            '报告', '研报', '研究报告', '投研', '投研报告', '深度研究',
            '基本面分析', '估值分析', '财报分析', '价值分析', '投资价值',
            '公司研究', '财务分析', '行业分析',
            'detailed analysis', 'in-depth analysis', 'comprehensive analysis',
            'investment analysis', 'fundamental analysis', 'valuation analysis',
            'report', 'research report',
            'worth buying', 'should i buy', 'buy or sell',
            '值得投资吗', '能买吗', '可以买吗', '要不要买',
            '值得买吗', '能投吗', '可以投吗', '要不要投',
            '前景如何', '未来走势如何', '长期怎么看',
        ]
        # 简单查询关键词（优先匹配为 CHAT，即使包含"分析"）
        simple_query_indicators = [
            '占比', '比例', '权重', '成分', '构成', '组成',
            '多少', '几个', '哪些', '有什么', '是什么',
            '查一下', '看一下', '帮我查', '帮我看',
            '简单', '快速', '大概', '大致',
        ]
        # 如果包含简单查询指示词，优先走 CHAT
        if any(kw in query_lower for kw in simple_query_indicators):
            if metadata.get('tickers') or self._contains_financial_keywords(query_lower):
                return Intent.CHAT
        # === 2.1 明确分析请求（含"分析"/analyze/analysis），且具备金融上下文 ===
        analysis_keywords = [
            '分析', 'analyze', 'analysis', 'research', '研报', '研究'
        ]
        if any(kw in query_lower for kw in analysis_keywords):
            has_financial_context = (
                self._contains_financial_keywords(query_lower)
                or bool(metadata.get('tickers'))
                or bool(metadata.get('company_names'))
                or bool(metadata.get('company_mentions'))
            )
            if has_financial_context and (
                metadata.get('tickers') or metadata.get('company_names') or metadata.get('company_mentions')
            ):
                return Intent.REPORT
        if any(kw in query_lower for kw in report_keywords):
            has_financial_context = (
                self._contains_financial_keywords(query_lower)
                or bool(metadata.get('tickers'))
                or bool(metadata.get('company_names'))
                or bool(metadata.get('company_mentions'))
            )
            if has_financial_context:
                return Intent.REPORT
        
        # === 3. 监控/提醒关键词 ===
        alert_keywords = [
            '提醒', '监控', '盯着', '通知', '预警',
            'alert', 'notify', 'watch', 'monitor', 'track',
            '跌破', '涨到', '到达', '突破', '跌到', '涨破',
            '价格到', '股价到', '低于', '高于',
        ]
        if any(kw in query_lower for kw in alert_keywords):
            return Intent.ALERT

        news_sentiment_keywords = [
            '新闻情绪', '舆情', '舆情指数', '媒体情绪', 'news sentiment', 'headline sentiment',
            'sentiment of news', 'media sentiment'
        ]
        if any(kw in query_lower for kw in news_sentiment_keywords):
            return Intent.NEWS_SENTIMENT
        if '情绪' in query_lower and any(kw in query_lower for kw in ['新闻', '快讯', 'headline', 'news']):
            return Intent.NEWS_SENTIMENT

        economic_event_keywords = [
            '经济日历', '宏观日历', '经济事件', '宏观事件', '经济数据', '数据公布',
            '非农', 'cpi', 'ppi', 'gdp', 'pmi', 'fomc', '利率决议', '央行会议',
            'economic calendar', 'economic events', 'macro events', 'macro calendar'
        ]
        if any(kw in query_lower for kw in economic_event_keywords):
            return Intent.ECONOMIC_EVENTS

        sentiment_strong = [
            '恐惧贪婪', '恐惧', '贪婪', '恐慌', 'fear & greed', 'fear and greed',
            'fear&greed', '情绪指标', '风险偏好', 'risk appetite'
        ]
        sentiment_soft = ['情绪', 'sentiment']
        sentiment_context = [
            '市场', '股市', '美股', '大盘', '指数', '投资者', 'market', 'index', 'equity'
        ]
        if any(kw in query_lower for kw in sentiment_strong):
            return Intent.CHAT
        if any(kw in query_lower for kw in sentiment_soft) and any(ctx in query_lower for ctx in sentiment_context):
            return Intent.CHAT

        # === 4. 市场新闻/热点 ===
        market_news_terms = [
            '热点', '新闻', '快讯', '头条', 'headline', 'breaking', 'news'
        ]
        market_context_terms = [
            '市场', '股市', '财经', '金融', '大盘', '指数', '宏观', '美股', '港股', 'a股', '行业', 'market'
        ]
        if any(kw in query_lower for kw in market_news_terms) and any(ctx in query_lower for ctx in market_context_terms):
            return Intent.CHAT
        
        # === 5. 对比/比较查询 ===
        comparison_keywords = ['对比', '比较', '区别', '差异', '不同', 'compare', 'vs', 'versus', 'difference', 'different']
        if any(kw in query_lower for kw in comparison_keywords):
            # 检查是否包含多个股票/指数
            connectors = ['和', '与', '及', '以及', 'and', '&', '、']
            has_multiple = any(conn in query for conn in connectors)
            if has_multiple:
                return Intent.CHAT
        
        # === 6. 追问关键词 ===
        followup_keywords = [
            '为什么', '详细说说', '具体说说', '展开说说', '解释一下',
            '风险呢', '优势呢', '缺点呢', '继续', '接着说',
            '风险在哪', '有什么风险', '有什么优势', '优点是什么',
            '竞争对手', '竞品', '同行', '对手是谁',
            'why', 'more details', 'explain', 'elaborate', 'go on',
            '什么意思', '不明白', '再说一下', '能解释',
        ]
        if any(kw in query_lower for kw in followup_keywords):
            # 检查是否有上下文
            if context_summary and context_summary != "无历史对话":
                return Intent.FOLLOWUP
            else:
                if metadata is not None:
                    metadata["clarify_reason"] = "followup_without_context"
                return Intent.CLARIFY  # 没有上下文时需要澄清

        # 6.1 针对“上一份/翻译/总结/报告”类，若有最近长文本则直接视为跟进
        followup_report_keywords = ['翻译', 'translate', '总结', '结论', '要点', '上一', '刚才', '上面', '报告', '上条', '上次']
        if last_long_response and any(kw in query_lower for kw in followup_report_keywords):
            return Intent.FOLLOWUP
        
        # === 7. 简单价格/信息查询 (CHAT) ===
        simple_query_keywords = [
            '多少钱', '股价', '现价', '价格', '收盘价', '开盘价',
            'price', 'how much', 'current', 'stock price',
            '今天', 'today', '涨了吗', '跌了吗', '行情',
            '最新', '实时', '现在',
        ]
        if any(kw in query_lower for kw in simple_query_keywords):
            return Intent.CHAT
        
        # === 8. 模糊查询 ===
        vague_patterns = [
            r'^它怎么样[？?]?$',
            r'^那个呢[？?]?$',
            r'^这个呢[？?]?$',
            r'^怎么样[？?]?$',
            r'^how about it[？?]?$',
            r'^what about it[？?]?$',
        ]
        for pattern in vague_patterns:
            if re.match(pattern, query_lower):
                # 如果有当前焦点，可以处理
                if context_summary and "当前焦点:" in context_summary:
                    return Intent.CHAT
                return Intent.CLARIFY
        
        return None  # 交给 LLM 或后续逻辑判断

    def _contains_financial_keywords(self, query: str) -> bool:
        """检查查询是否包含金融相关关键词"""
        query_lower = query.lower()
        financial_keywords = [
            '股票', '基金', '指数', 'etf', '价格', '走势', '分析', '报告', '投资', '行情',
            '研报', '投研', '基本面', '估值', '财报', '业绩', '市值', '营收', '利润',
            '市场', '股市', '财经', '金融', '新闻', '热点', '快讯', '头条',
            '情绪', '恐惧', '贪婪', '恐慌', '风险偏好', 'sentiment', 'fear', 'greed', 'risk appetite',
            '宏观', '经济日历', '经济事件', '宏观事件', '经济数据', 'fomc', 'cpi', 'ppi', 'gdp', 'pmi',
            'ticker', 'stock', 'price', 'analyze', 'report', 'market', 'finance',
            'fundamental', 'valuation', 'earnings', 'financials'
        ]
        return any(kw in query_lower for kw in financial_keywords)
    
    def _llm_classify(self, query: str, context_summary: str, metadata: Dict[str, Any] = None) -> Intent:
        """使用 LLM 进行意图分类（主要方法）"""
        from langchain_core.messages import HumanMessage
        
        # 构建上下文信息
        context_info = context_summary if context_summary else "无历史对话"
        tickers_info = ""
        if metadata and metadata.get('tickers'):
            tickers_info = f"\n识别到的股票/指数: {', '.join(metadata['tickers'])}"
            if metadata and metadata.get('company_mentions'):
                tickers_info += '\nCompany mentions: ' + ', '.join(metadata['company_mentions'])
        
        try:
            prompt = f"""You are a professional financial dialogue system intent classifier. Analyze the user's query intent.

User Query: {query}
Conversation Context: {context_info}
{tickers_info}

Analyze the user's intent and choose ONE from the following options:

1. **CHAT** - Quick Financial Q&A
    - Price queries ("how much", "current price")
    - Simple info/comparison ("what is", "introduction", "A vs B")
    - Investment advice ("suggest", "recommend")
    - MUST involve financial topics or specific tickers.

2. **REPORT** - Deep Analysis Report
    - Explicit analysis requests ("analyze XXX", "detailed analysis")
    - "worth investing", "should I buy", "future trend"

3. **ALERT** - Monitoring & Alerts
    - "remind me", "monitor", "watch", "drops below XXX"

4. **ECONOMIC_EVENTS** - Economic calendar / macro events
    - "economic calendar", "macro events", "CPI", "FOMC", "NFP"

5. **NEWS_SENTIMENT** - News sentiment / media sentiment
    - "news sentiment", "headline sentiment", "舆情"

6. **FOLLOWUP** - Follow-up Questions
    - Requires context ("why", "tell me more", "what about risks")

7. **GREETING** - Greeting / Small Talk
    - "Hello", "Hi", "Who are you", "Introduce yourself"
    - Non-financial general chat.

8. **CLARIFY** - Unclear / Irrelevant
    - Queries unrelated to finance (e.g., "write a bubble sort", "weather today")
    - Missing key info (no stock ticker or context)
    - Unclear intent

Respond with ONLY the intent name (CHAT/REPORT/ALERT/ECONOMIC_EVENTS/NEWS_SENTIMENT/FOLLOWUP/GREETING/CLARIFY), nothing else."""

            response = self.llm.invoke([HumanMessage(content=prompt)])
            intent_str = response.content.strip().upper()
            
            # 提取意图（可能包含其他文本）
            for intent_name in ['CHAT', 'REPORT', 'ALERT', 'ECONOMIC_EVENTS', 'NEWS_SENTIMENT', 'FOLLOWUP', 'CLARIFY', 'GREETING']:
                if intent_name in intent_str:
                    intent_str = intent_name
                    break
            
            # 映射到 Intent 枚举
            intent_map = {
                'CHAT': Intent.CHAT,
                'REPORT': Intent.REPORT,
                'ALERT': Intent.ALERT,
                'ECONOMIC_EVENTS': Intent.ECONOMIC_EVENTS,
                'NEWS_SENTIMENT': Intent.NEWS_SENTIMENT,
                'FOLLOWUP': Intent.FOLLOWUP,
                'CLARIFY': Intent.CLARIFY,
                'GREETING': Intent.GREETING,
            }
            
            result = intent_map.get(intent_str, Intent.CLARIFY) # 默认回退到 CLARIFY
            logger.info(f"[Router] LLM 意图识别: {query[:50]}... -> {result.value}")
            return result
            
        except Exception as e:
            logger.info(f"[Router] LLM 分类失败: {e}")
            return Intent.CHAT
    
    def _extract_metadata(self, query: str) -> Dict[str, Any]:
        """Extract metadata from query using shared ticker extraction"""
        # Use shared extraction function
        metadata = extract_tickers(query)
        metadata['raw_query'] = query

        # Detect company mentions not resolved to tickers
        query_original = query
        company_mentions = []
        stopwords = {
            'news', 'headline', 'analysis', 'report', 'price', 'forecast', 'outlook', 'expectation',
            'earnings', 'market', 'stock', 'shares', 'company', 'rating', 'recommendation', 'guidance',
            'latest', 'today', 'ytd', 'q1', 'q2', 'q3', 'q4', 'eps', 'pe', 'roe', 'revenue', 'profit'
        }
        english_candidates = re.findall(r"[A-Za-z][A-Za-z&.'-]{2,}", query_original)
        for candidate in english_candidates:
            lower = candidate.lower()
            if lower in stopwords or lower in COMPANY_MAP:
                continue
            if candidate.upper() in metadata['tickers']:
                continue
            if any(lower == name.lower() for name in metadata['company_names']):
                continue
            if candidate not in company_mentions:
                company_mentions.append(candidate)

        cn_candidates = re.findall(r"([\u4e00-\u9fff]{2,6})(?:公司|集团|股份|控股)", query_original)
        for candidate in cn_candidates:
            if candidate in CN_TO_TICKER or candidate in metadata['company_names']:
                continue
            if candidate not in company_mentions:
                company_mentions.append(candidate)

        metadata['company_mentions'] = company_mentions
        return metadata
