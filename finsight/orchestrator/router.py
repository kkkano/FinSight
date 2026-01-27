"""
意图路由器 - 软路由实现

设计原则：
1. LLM 优先：使用 LLM 进行意图分类
2. 规则兜底：LLM 失败或置信度低时使用规则
3. 置信度阈值：低于阈值触发追问
4. 可扩展：支持新增意图和规则
"""

import re
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

from finsight.domain.models import (
    Intent,
    RouteDecision,
    ClarifyQuestion,
    AnalysisRequest,
)
from finsight.ports.interfaces import LLMPort


@dataclass
class TickerExtraction:
    """Ticker 提取结果"""
    tickers: List[str]
    confidence: float
    method: str  # "regex", "llm", "both"


class Router:
    """
    意图路由器

    职责：
    1. 从用户查询中提取 ticker
    2. 分类用户意图
    3. 决定是否需要追问
    """

    # 置信度阈值
    HIGH_CONFIDENCE = 0.8
    LOW_CONFIDENCE = 0.5

    # 常见股票代码模式
    TICKER_PATTERNS = [
        r'\b([A-Z]{1,5})\b',              # 美股代码 (1-5大写字母)
        r'\$([A-Z]{1,5})\b',              # $符号前缀
        r'\b([A-Z]{1,4}\.[A-Z]{1,2})\b',  # 带交易所后缀 (如 BABA.HK)
        r'\b(\d{6})\.(SH|SZ)\b',          # A股代码
    ]

    # 常见股票别名映射
    TICKER_ALIASES = {
        # 科技巨头
        "苹果": "AAPL", "apple": "AAPL",
        "谷歌": "GOOGL", "google": "GOOGL", "alphabet": "GOOGL",
        "微软": "MSFT", "microsoft": "MSFT",
        "亚马逊": "AMZN", "amazon": "AMZN",
        "特斯拉": "TSLA", "tesla": "TSLA",
        "英伟达": "NVDA", "nvidia": "NVDA",
        "脸书": "META", "facebook": "META", "meta": "META",
        "奈飞": "NFLX", "netflix": "NFLX",
        # 中概股
        "阿里巴巴": "BABA", "alibaba": "BABA", "阿里": "BABA",
        "腾讯": "TCEHY", "tencent": "TCEHY",
        "百度": "BIDU", "baidu": "BIDU",
        "京东": "JD", "jd": "JD",
        "拼多多": "PDD", "pinduoduo": "PDD",
        "网易": "NTES", "netease": "NTES",
        # 指数
        "标普": "SPY", "sp500": "SPY", "s&p500": "SPY", "标普500": "SPY",
        "纳斯达克": "QQQ", "nasdaq": "QQQ",
        "道琼斯": "DIA", "dow jones": "DIA",
        # 加密货币
        "比特币": "BTC-USD", "bitcoin": "BTC-USD", "btc": "BTC-USD",
        "以太坊": "ETH-USD", "ethereum": "ETH-USD", "eth": "ETH-USD",
    }

    # 意图关键词映射（规则兜底）
    INTENT_KEYWORDS = {
        Intent.STOCK_PRICE: [
            "价格", "股价", "多少钱", "行情", "报价",
            "price", "quote", "how much", "trading at"
        ],
        Intent.STOCK_NEWS: [
            "新闻", "消息", "动态", "资讯", "最新",
            "news", "headlines", "latest", "what happened"
        ],
        Intent.STOCK_ANALYSIS: [
            "分析", "研究", "深度", "报告", "评估", "投资",
            "analyze", "analysis", "research", "deep dive", "evaluate"
        ],
        Intent.COMPANY_INFO: [
            "公司信息", "公司简介", "基本信息", "介绍",
            "company info", "about", "profile", "overview"
        ],
        Intent.COMPARE_ASSETS: [
            "对比", "比较", "哪个好", "vs", "versus",
            "compare", "comparison", "which is better"
        ],
        Intent.MARKET_SENTIMENT: [
            "情绪", "恐惧", "贪婪", "市场情绪", "fear", "greed",
            "sentiment", "market mood", "fear and greed"
        ],
        Intent.MACRO_EVENTS: [
            "经济日历", "宏观", "fed", "fomc", "cpi", "gdp",
            "economic calendar", "macro", "interest rate"
        ],
        Intent.HISTORICAL_ANALYSIS: [
            "回撤", "历史", "drawdown", "historical",
            "maximum drawdown", "mdd", "跌幅"
        ],
        Intent.GENERAL_SEARCH: [
            "搜索", "查询", "找", "search", "find", "look up"
        ],
    }

    def __init__(self, llm_port: Optional[LLMPort] = None):
        """
        初始化路由器

        Args:
            llm_port: LLM 端口（可选，用于智能路由）
        """
        self.llm = llm_port

    def route(self, request: AnalysisRequest) -> RouteDecision:
        """
        执行路由决策

        Args:
            request: 分析请求

        Returns:
            RouteDecision: 路由决策结果
        """
        query = request.query.strip()
        extracted_params: Dict = {}

        # 1. 提取 ticker
        ticker_result = self._extract_tickers(query)
        if ticker_result.tickers:
            if len(ticker_result.tickers) == 1:
                extracted_params["ticker"] = ticker_result.tickers[0]
            else:
                extracted_params["tickers"] = ticker_result.tickers

        # 2. 如果有预设的 intent hint，直接使用
        if request.intent_hint:
            return RouteDecision(
                intent=request.intent_hint,
                confidence=1.0,
                extracted_params=extracted_params,
            )

        # 3. 尝试 LLM 分类
        if self.llm:
            try:
                llm_decision = self.llm.classify_intent(query)

                # 合并提取的参数
                merged_params = {**llm_decision.extracted_params, **extracted_params}

                # 如果 LLM 返回需要追问
                if llm_decision.needs_clarification:
                    return RouteDecision(
                        intent=llm_decision.intent,
                        confidence=llm_decision.confidence,
                        extracted_params=merged_params,
                        needs_clarification=True,
                        clarify_question=llm_decision.clarify_question,
                        missing_fields=llm_decision.missing_fields,
                    )

                # 高置信度直接返回
                if llm_decision.confidence >= self.HIGH_CONFIDENCE:
                    return RouteDecision(
                        intent=llm_decision.intent,
                        confidence=llm_decision.confidence,
                        extracted_params=merged_params,
                    )

                # 中等置信度，结合规则验证
                if llm_decision.confidence >= self.LOW_CONFIDENCE:
                    rule_intent, rule_conf = self._rule_based_classify(query)
                    if rule_intent == llm_decision.intent:
                        # 规则验证通过，提升置信度
                        return RouteDecision(
                            intent=llm_decision.intent,
                            confidence=min(llm_decision.confidence + 0.1, 1.0),
                            extracted_params=merged_params,
                        )
                    # 规则和 LLM 不一致，保持 LLM 结果但标记
                    return RouteDecision(
                        intent=llm_decision.intent,
                        confidence=llm_decision.confidence,
                        extracted_params=merged_params,
                    )

                # 低置信度，触发追问
                return self._create_clarification_decision(
                    query, llm_decision.intent, extracted_params
                )

            except Exception:
                # LLM 失败，降级到规则
                pass

        # 4. 规则兜底
        rule_intent, rule_confidence = self._rule_based_classify(query)

        # 如果规则也无法确定
        if rule_intent == Intent.UNCLEAR or rule_confidence < self.LOW_CONFIDENCE:
            return self._create_clarification_decision(
                query, rule_intent, extracted_params
            )

        # 检查必要参数
        missing = self._check_missing_params(rule_intent, extracted_params)
        if missing:
            return RouteDecision(
                intent=rule_intent,
                confidence=rule_confidence,
                extracted_params=extracted_params,
                needs_clarification=True,
                missing_fields=missing,
                clarify_question=ClarifyQuestion(
                    question=self._generate_missing_param_question(missing[0]),
                    field_name=missing[0],
                    reason="缺少必要参数",
                ),
            )

        return RouteDecision(
            intent=rule_intent,
            confidence=rule_confidence,
            extracted_params=extracted_params,
        )

    def _extract_tickers(self, query: str) -> TickerExtraction:
        """
        从查询中提取股票代码

        Args:
            query: 用户查询

        Returns:
            TickerExtraction: 提取结果
        """
        tickers = []
        query_lower = query.lower()

        # 1. 检查别名映射
        for alias, ticker in self.TICKER_ALIASES.items():
            if alias in query_lower:
                if ticker not in tickers:
                    tickers.append(ticker)

        # 2. 正则匹配
        for pattern in self.TICKER_PATTERNS:
            matches = re.findall(pattern, query.upper())
            for match in matches:
                # 处理元组（带捕获组的情况）
                ticker = match[0] if isinstance(match, tuple) else match
                # 过滤常见非股票词汇
                if ticker not in ["I", "A", "THE", "AND", "OR", "TO", "IS", "IT", "FOR"]:
                    if ticker not in tickers:
                        tickers.append(ticker)

        confidence = 0.9 if tickers else 0.0
        return TickerExtraction(
            tickers=tickers,
            confidence=confidence,
            method="regex" if not self.llm else "both"
        )

    def _rule_based_classify(self, query: str) -> Tuple[Intent, float]:
        """
        基于规则的意图分类

        Args:
            query: 用户查询

        Returns:
            Tuple[Intent, float]: (意图, 置信度)
        """
        query_lower = query.lower()
        scores: Dict[Intent, int] = {intent: 0 for intent in Intent}

        # 计算每个意图的匹配分数
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    scores[intent] += 1

        # 找出最高分的意图
        max_intent = max(scores, key=scores.get)
        max_score = scores[max_intent]

        if max_score == 0:
            # 没有匹配，检查是否有 ticker（默认股票分析）
            ticker_result = self._extract_tickers(query)
            if ticker_result.tickers:
                return Intent.STOCK_ANALYSIS, 0.6
            return Intent.UNCLEAR, 0.3

        # 计算置信度
        total_keywords = sum(len(kw) for kw in self.INTENT_KEYWORDS.values())
        confidence = min(0.5 + (max_score * 0.15), 0.85)

        return max_intent, confidence

    def _check_missing_params(
        self,
        intent: Intent,
        params: Dict
    ) -> List[str]:
        """检查缺失的必要参数"""
        missing = []

        # 需要 ticker 的意图
        ticker_required_intents = [
            Intent.STOCK_PRICE,
            Intent.STOCK_NEWS,
            Intent.STOCK_ANALYSIS,
            Intent.COMPANY_INFO,
            Intent.HISTORICAL_ANALYSIS,
        ]

        if intent in ticker_required_intents:
            if "ticker" not in params and "tickers" not in params:
                missing.append("ticker")

        # 资产对比需要多个 ticker
        if intent == Intent.COMPARE_ASSETS:
            tickers = params.get("tickers", [])
            if len(tickers) < 2:
                if "ticker" in params:
                    # 只有一个，需要更多
                    missing.append("more_tickers")
                else:
                    missing.append("tickers")

        return missing

    def _generate_missing_param_question(self, field: str) -> str:
        """生成缺失参数的追问问题"""
        questions = {
            "ticker": "请问您想查询哪只股票？请提供股票代码或公司名称。",
            "tickers": "请问您想对比哪些资产？请提供至少两个股票代码。",
            "more_tickers": "您想将它与哪些其他资产进行对比？请再提供至少一个股票代码。",
        }
        return questions.get(field, f"请提供 {field} 信息。")

    def _create_clarification_decision(
        self,
        query: str,
        suggested_intent: Intent,
        extracted_params: Dict
    ) -> RouteDecision:
        """创建需要追问的路由决策"""
        # 生成追问选项
        options = [
            "查看股票实时价格",
            "获取股票相关新闻",
            "进行深度投资分析",
            "查看市场情绪指标",
            "比较多个资产表现",
            "查看经济日历",
        ]

        return RouteDecision(
            intent=suggested_intent,
            confidence=0.4,
            extracted_params=extracted_params,
            needs_clarification=True,
            clarify_question=ClarifyQuestion(
                question="我不太确定您的具体需求，请选择您想要的服务：",
                options=options,
                field_name="intent",
                reason="意图识别置信度较低",
            ),
        )
