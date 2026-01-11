# -*- coding: utf-8 -*-
"""
ConversationRouter - 对话路由器
负责意图识别和模式分发
"""

from enum import Enum
from typing import Tuple, Dict, Any, Optional, List, Callable
import re

# 假设 ContextManager 在 .context 模块中。如果不在，请修改此行
try:
    # 尝试相对导入，假设 ContextManager 在同一目录下的 context.py 中
    from .context import ContextManager
except ImportError:
    # 如果您没有 ContextManager，可能需要定义一个空的占位符或修改 route 方法签名
    class ContextManager:
        def get_context_summary(self) -> str:
            return "无历史对话"
        def update_context(self, intent: Enum, metadata: Dict[str, Any]):
            pass


class Intent(Enum):
    """意图类型"""
    CHAT = "chat"          # 快速问答 (涉及金融数据)
    REPORT = "report"      # 深度报告
    ALERT = "alert"        # 监控订阅
    ECONOMIC_EVENTS = "economic_events"  # 经济日历/宏观事件
    NEWS_SENTIMENT = "news_sentiment"    # 新闻情绪/舆情
    CLARIFY = "clarify"    # 需要澄清/无法识别/非金融问题
    FOLLOWUP = "followup"  # 追问上文
    GREETING = "greeting"  # 问候/闲聊/自我介绍 (新增)


class ConversationRouter:
    """
    对话路由器
    
    功能：
    - 意图识别（规则 + LLM 混合）
    - 元数据提取（股票代码、公司名）
    - 路由到对应处理器
    """
    
    # 股票代码到公司名映射
    COMPANY_MAP = {
        # 美股科技
        'AAPL': '苹果', 'apple': 'AAPL',
        'GOOGL': '谷歌', 'google': 'GOOGL', 'alphabet': 'GOOGL',
        'GOOG': '谷歌',
        'MSFT': '微软', 'microsoft': 'MSFT',
        'AMZN': '亚马逊', 'amazon': 'AMZN',
        'META': 'Meta', 'facebook': 'META',
        'TSLA': '特斯拉', 'tesla': 'TSLA',
        'NVDA': '英伟达', 'nvidia': 'NVDA',
        'AMD': 'AMD',
        'INTC': '英特尔', 'intel': 'INTC',
        'NFLX': '奈飞', 'netflix': 'NFLX',
        'CRM': 'Salesforce', 'salesforce': 'CRM',
        # 中概股
        'BABA': '阿里巴巴', 'alibaba': 'BABA',
        'JD': '京东', 'jd': 'JD',
        'PDD': '拼多多', 'pinduoduo': 'PDD',
        'BIDU': '百度', 'baidu': 'BIDU',
        'NIO': '蔚来', 'nio': 'NIO',
        'XPEV': '小鹏', 'xpeng': 'XPEV',
        'LI': '理想', 'li auto': 'LI',
        # ETF 和指数
        'SPY': 'S&P 500 ETF',
        'QQQ': 'Nasdaq 100 ETF',
        'DIA': 'Dow Jones ETF',
        'IWM': 'Russell 2000 ETF',
        'VTI': 'Total Stock Market ETF',
    }
    
    # 中文名到股票代码映射
    CN_TO_TICKER = {
        '苹果': 'AAPL', '谷歌': 'GOOGL', '微软': 'MSFT',
        '亚马逊': 'AMZN', '特斯拉': 'TSLA', '英伟达': 'NVDA',
        '阿里巴巴': 'BABA', '阿里': 'BABA', '京东': 'JD',
        '拼多多': 'PDD', '百度': 'BIDU', '英特尔': 'INTC',
        '蔚来': 'NIO', '小鹏': 'XPEV', '理想': 'LI',
        '凯捷': 'CAP.PA',
        '奈飞': 'NFLX', '脸书': 'META', 'Facebook': 'META',
        # 市场指数
        '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
        '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
        '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC', 'sp500': '^GSPC',
        '罗素2000': '^RUT', 'VIX': '^VIX', '恐慌指数': '^VIX',
        '纽交所': '^NYA', '纽交所指数': '^NYA',
        '富时100': '^FTSE', '日经225': '^N225', '恒生指数': '^HSI',
    }
    
    # 市场指数别名映射（更全面的识别）
    INDEX_ALIASES = {
        # 纳斯达克
        '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
        'nasdaq': '^IXIC', 'nasdaq composite': '^IXIC',
        # 道琼斯
        '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
        'dow jones': '^DJI', 'dow': '^DJI',
        # 标普500
        '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC',
        'sp500': '^GSPC', 'sp 500': '^GSPC', '标准普尔500': '^GSPC',
        # 其他指数
        '罗素2000': '^RUT', 'russell 2000': '^RUT',
        'VIX': '^VIX', '恐慌指数': '^VIX', 'vix指数': '^VIX',
        '纽交所': '^NYA', '纽交所指数': '^NYA', 'nyse': '^NYA',
    }
    
    def __init__(self, llm=None):
        """
        初始化路由器
        
        Args:
            llm: LLM 实例，用于复杂意图分类（可选）
        """
        self.llm = llm
        self._handlers: Dict[Intent, Callable] = {}
    
    def register_handler(self, intent: Intent, handler: Callable) -> None:
        """注册意图处理器"""
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
                print(
                    "[Router] LLM fallback start"
                    f" reason={fallback_reason}"
                    f" query={query!r}"
                    f" tickers={metadata.get('tickers', [])}"
                    f" company_names={metadata.get('company_names', [])}"
                )
                try:
                    llm_intent = self._llm_classify(query, context_summary, metadata)
                    print(
                        "[Router] LLM fallback result"
                        f" reason={fallback_reason}"
                        f" intent={llm_intent.value}"
                        f" query={query!r}"
                    )
                    return llm_intent, metadata
                except Exception as e:
                    print(f"[Router] LLM 意图识别失败: {e}，回退到规则匹配")

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

        # === 2. 报告关键词 ===
        report_keywords = [
            '分析', '报告', '详细分析', '深度分析', '全面分析', '投资分析',
            '研报', '研究报告', '投研', '投研报告', '深度研究',
            '基本面', '估值', '财报', '业绩', '价值分析', '投资价值',
            '公司研究', '财务分析',
            'analyze', 'analysis', 'report', 'detailed', 'comprehensive',
            'fundamental analysis', 'valuation', 'earnings', 'financials',
            'worth buying', 'should i buy', 'buy or sell',
            '值得投资吗', '能买吗', '可以买吗', '要不要买',
            '值得买吗', '能投吗', '可以投吗', '要不要投',
            '怎么看', '看好吗', '前景如何', '未来走势',
        ]
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
            print(f"[Router] LLM 意图识别: {query[:50]}... -> {result.value}")
            return result
            
        except Exception as e:
            print(f"[Router] LLM 分类失败: {e}")
            return Intent.CHAT
    
    def _extract_metadata(self, query: str) -> Dict[str, Any]:
        """
        从查询中提取元数据
        """
        metadata = {
            'tickers': [],
            'company_names': [],
            'company_mentions': [],
            'raw_query': query,
            'is_comparison': False
        }
        
        query_lower = query.lower()
        query_original = query  # 保留原始查询用于中文匹配
        
        # 0. 检查是否为对比查询
        comparison_keywords = ['对比', '比较', 'vs', 'versus', '区别', '差异', 'compare']
        if any(kw in query_lower for kw in comparison_keywords):
            metadata['is_comparison'] = True

        # 1. 优先识别市场指数（最长匹配优先）
        sorted_aliases = sorted(self.INDEX_ALIASES.keys(), key=len, reverse=True)
        
        for alias in sorted_aliases:
            # 使用 regex 确保匹配完整词 (英文) 或 直接匹配 (中文)
            pattern = re.compile(re.escape(alias), re.IGNORECASE)
            if pattern.search(query_original):
                ticker = self.INDEX_ALIASES[alias]
                if ticker not in metadata['tickers']:
                    metadata['tickers'].append(ticker)
                    metadata['company_names'].append(alias)
        
        # 2. 识别英文 Ticker
        # 匹配 1-5 位大写字母，或者是 ^ 开头的指数
        potential_tickers = re.findall(r'\b[A-Z]{1,5}\b|\^[A-Z]{3,}', query)
        dotted_tickers = re.findall(r'\b[A-Z]{1,5}[.-][A-Z]{1,4}\b', query)
        if dotted_tickers:
            potential_tickers.extend(dotted_tickers)

        # 过滤掉常见的非 Ticker 单词
        common_words = {'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS', 'PE', 'EPS', 'MACD', 'RSI', 'KDJ'}

        # 已知的有效 ticker 列表（直接使用，不转换）
        known_tickers = {'AAPL', 'GOOGL', 'GOOG', 'MSFT', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD', 'INTC',
                         'NFLX', 'CRM', 'BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'XPEV', 'LI',
                         'SPY', 'QQQ', 'DIA', 'IWM', 'VTI'}

        for ticker in potential_tickers:
            if ticker in common_words:
                continue

            # 如果是已知的有效 ticker，直接使用（不要转换成中文！）
            if ticker in known_tickers or ticker.startswith('^'):
                if ticker not in metadata['tickers']:
                    metadata['tickers'].append(ticker)
            # 检查是否是英文公司名（如 apple -> AAPL）
            elif ticker.lower() in self.COMPANY_MAP:
                real_ticker = self.COMPANY_MAP.get(ticker.lower())
                if real_ticker and real_ticker not in metadata['tickers']:
                    metadata['tickers'].append(real_ticker)
            else:
                # 未知 ticker，假设它是有效的
                if ticker not in metadata['tickers']:
                    metadata['tickers'].append(ticker)

        # 3. 识别中文公司名/别名
        sorted_cn_names = sorted(self.CN_TO_TICKER.keys(), key=len, reverse=True)
        
        for cn_name in sorted_cn_names:
            if cn_name in query_original:
                ticker = self.CN_TO_TICKER[cn_name]
                # 避免重复添加
                if ticker not in metadata['tickers']:
                    metadata['tickers'].append(ticker)
                    metadata['company_names'].append(cn_name)
        
        # 4. 识别英文公司名（全名）
        for name, ticker in self.COMPANY_MAP.items():
            if len(name) > 4 and name.lower() in query_lower:  # 忽略短词
                 if ticker not in metadata['tickers']:
                     metadata['tickers'].append(ticker)
                     metadata['company_names'].append(name)

        # 5. Detect explicit company mentions that are not resolved to tickers.
        # This prevents accidental reuse of previous context when a new company is named.
        company_mentions = []
        stopwords = {
            'news', 'headline', 'analysis', 'report', 'price', 'forecast', 'outlook', 'expectation',
            'earnings', 'market', 'stock', 'shares', 'company', 'rating', 'recommendation', 'guidance',
            'latest', 'today', 'ytd', 'q1', 'q2', 'q3', 'q4', 'eps', 'pe', 'roe', 'revenue', 'profit'
        }
        english_candidates = re.findall(r"[A-Za-z][A-Za-z&.'-]{2,}", query_original)
        for candidate in english_candidates:
            lower = candidate.lower()
            if lower in stopwords:
                continue
            if lower in self.COMPANY_MAP:
                continue
            if candidate.upper() in metadata['tickers']:
                continue
            if any(lower == name.lower() for name in metadata['company_names']):
                continue
            if candidate not in company_mentions:
                company_mentions.append(candidate)

        cn_candidates = re.findall(r"([\u4e00-\u9fff]{2,6})(?:公司|集团|股份|控股)", query_original)
        for candidate in cn_candidates:
            if candidate in self.CN_TO_TICKER:
                continue
            if candidate in metadata['company_names']:
                continue
            if candidate not in company_mentions:
                company_mentions.append(candidate)

        metadata['company_mentions'] = company_mentions
        
        return metadata
