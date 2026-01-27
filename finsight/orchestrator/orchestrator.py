"""
请求编排器 - 统一请求处理入口

设计原则：
1. 单一入口：所有请求通过 Orchestrator 处理
2. 依赖注入：所有依赖通过构造函数注入
3. 错误隔离：每个用例的错误不影响其他用例
4. 可观测性：记录所有关键操作
"""

import time
import uuid
from typing import Optional, Dict, Type
from datetime import datetime

from finsight.domain.models import (
    Intent,
    AnalysisRequest,
    AnalysisResult,
    ResponseMode,
    ErrorCode,
    ClarifyQuestion,
)
from finsight.ports.interfaces import (
    MarketDataPort,
    NewsPort,
    SentimentPort,
    SearchPort,
    TimePort,
    LLMPort,
)
from finsight.orchestrator.router import Router
from finsight.use_cases.base import AnalysisUseCase


class Orchestrator:
    """
    请求编排器

    职责：
    1. 接收 AnalysisRequest
    2. 调用 Router 进行意图识别
    3. 执行对应的 Use Case
    4. 返回 AnalysisResult
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        news_port: NewsPort,
        sentiment_port: SentimentPort,
        search_port: SearchPort,
        time_port: TimePort,
        llm_port: Optional[LLMPort] = None,
    ):
        """
        初始化编排器

        Args:
            market_data_port: 市场数据端口
            news_port: 新闻端口
            sentiment_port: 情绪端口
            search_port: 搜索端口
            time_port: 时间端口
            llm_port: LLM 端口（可选）
        """
        self.market_data = market_data_port
        self.news = news_port
        self.sentiment = sentiment_port
        self.search = search_port
        self.time = time_port
        self.llm = llm_port

        # 初始化路由器
        self.router = Router(llm_port=llm_port)

        # 延迟导入用例，避免循环依赖
        self._use_cases: Dict[Intent, Type[AnalysisUseCase]] = {}
        self._initialized = False

    def _lazy_init(self):
        """延迟初始化用例映射"""
        if self._initialized:
            return

        # 导入所有用例
        from finsight.use_cases.stock_price import GetStockPriceUseCase
        from finsight.use_cases.stock_news import GetStockNewsUseCase
        from finsight.use_cases.analyze_stock import AnalyzeStockUseCase
        from finsight.use_cases.compare_assets import CompareAssetsUseCase
        from finsight.use_cases.market_sentiment import GetMarketSentimentUseCase
        from finsight.use_cases.macro_events import GetMacroEventsUseCase

        # 映射意图到用例
        self._use_cases = {
            Intent.STOCK_PRICE: GetStockPriceUseCase,
            Intent.STOCK_NEWS: GetStockNewsUseCase,
            Intent.STOCK_ANALYSIS: AnalyzeStockUseCase,
            Intent.COMPANY_INFO: AnalyzeStockUseCase,  # 复用股票分析
            Intent.COMPARE_ASSETS: CompareAssetsUseCase,
            Intent.MARKET_SENTIMENT: GetMarketSentimentUseCase,
            Intent.MACRO_EVENTS: GetMacroEventsUseCase,
            Intent.HISTORICAL_ANALYSIS: GetStockPriceUseCase,  # TODO: 单独实现
            Intent.GENERAL_SEARCH: GetStockPriceUseCase,  # TODO: 单独实现
        }

        self._initialized = True

    def process(self, request: AnalysisRequest) -> AnalysisResult:
        """
        处理分析请求

        Args:
            request: 分析请求

        Returns:
            AnalysisResult: 分析结果
        """
        start_time = time.time()
        request_id = request.request_id or str(uuid.uuid4())

        # 延迟初始化
        self._lazy_init()

        try:
            # 1. 路由决策
            route_decision = self.router.route(request)

            # 2. 如果需要追问
            if route_decision.needs_clarification:
                return AnalysisResult(
                    request_id=request_id,
                    intent=route_decision.intent,
                    mode=request.mode,
                    needs_clarification=True,
                    clarify_question=route_decision.clarify_question,
                    tools_called=["router"],
                    latency_ms=int((time.time() - start_time) * 1000),
                )

            # 3. 获取用例
            use_case_class = self._use_cases.get(route_decision.intent)
            if not use_case_class:
                return self._create_error_result(
                    request_id=request_id,
                    intent=route_decision.intent,
                    mode=request.mode,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message=f"未实现的意图: {route_decision.intent.value}",
                    start_time=start_time,
                )

            # 4. 创建并执行用例
            use_case = self._create_use_case(use_case_class, route_decision.intent)
            result = self._execute_use_case(
                use_case=use_case,
                intent=route_decision.intent,
                params=route_decision.extracted_params,
                request_id=request_id,
                mode=request.mode,
            )

            # 5. 填充延迟信息
            result.latency_ms = int((time.time() - start_time) * 1000)
            result.tools_called.insert(0, "router")

            return result

        except Exception as e:
            return self._create_error_result(
                request_id=request_id,
                intent=Intent.UNCLEAR,
                mode=request.mode,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message=f"处理请求时发生错误: {str(e)}",
                start_time=start_time,
            )

    def _create_use_case(
        self,
        use_case_class: Type[AnalysisUseCase],
        intent: Intent
    ) -> AnalysisUseCase:
        """
        根据意图创建用例实例

        Args:
            use_case_class: 用例类
            intent: 意图

        Returns:
            AnalysisUseCase: 用例实例
        """
        # 导入用例类以检查依赖
        from finsight.use_cases.stock_price import GetStockPriceUseCase
        from finsight.use_cases.stock_news import GetStockNewsUseCase
        from finsight.use_cases.analyze_stock import AnalyzeStockUseCase
        from finsight.use_cases.compare_assets import CompareAssetsUseCase
        from finsight.use_cases.market_sentiment import GetMarketSentimentUseCase
        from finsight.use_cases.macro_events import GetMacroEventsUseCase

        # 根据用例类型注入不同依赖
        if use_case_class == GetStockPriceUseCase:
            return GetStockPriceUseCase(
                market_data_port=self.market_data,
                time_port=self.time,
            )
        elif use_case_class == GetStockNewsUseCase:
            return GetStockNewsUseCase(
                news_port=self.news,
                time_port=self.time,
            )
        elif use_case_class == AnalyzeStockUseCase:
            return AnalyzeStockUseCase(
                market_data_port=self.market_data,
                news_port=self.news,
                sentiment_port=self.sentiment,
                search_port=self.search,
                time_port=self.time,
                llm_port=self.llm,
            )
        elif use_case_class == CompareAssetsUseCase:
            return CompareAssetsUseCase(
                market_data_port=self.market_data,
                time_port=self.time,
            )
        elif use_case_class == GetMarketSentimentUseCase:
            return GetMarketSentimentUseCase(
                sentiment_port=self.sentiment,
                time_port=self.time,
            )
        elif use_case_class == GetMacroEventsUseCase:
            return GetMacroEventsUseCase(
                search_port=self.search,
                time_port=self.time,
            )
        else:
            raise ValueError(f"Unknown use case class: {use_case_class}")

    def _execute_use_case(
        self,
        use_case: AnalysisUseCase,
        intent: Intent,
        params: Dict,
        request_id: str,
        mode: ResponseMode,
    ) -> AnalysisResult:
        """
        执行用例

        Args:
            use_case: 用例实例
            intent: 意图
            params: 提取的参数
            request_id: 请求 ID
            mode: 响应模式

        Returns:
            AnalysisResult: 执行结果
        """
        # 根据不同意图调用不同的 execute 方法
        if intent in [Intent.STOCK_PRICE, Intent.STOCK_NEWS, Intent.STOCK_ANALYSIS, Intent.COMPANY_INFO]:
            ticker = params.get("ticker")
            if not ticker:
                return AnalysisResult(
                    request_id=request_id,
                    intent=intent,
                    mode=mode,
                    success=False,
                    error_code=ErrorCode.INVALID_INPUT,
                    error_message="缺少股票代码",
                    needs_clarification=True,
                    clarify_question=ClarifyQuestion(
                        question="请问您想查询哪只股票？",
                        field_name="ticker",
                        reason="缺少股票代码",
                    ),
                )
            return use_case.execute(
                ticker=ticker,
                request_id=request_id,
                mode=mode,
            )

        elif intent == Intent.COMPARE_ASSETS:
            tickers = params.get("tickers", [])
            if not tickers or len(tickers) < 2:
                # 如果只有一个 ticker，尝试构建对比
                single_ticker = params.get("ticker")
                if single_ticker:
                    # 默认与 SPY 对比
                    tickers = {single_ticker: single_ticker, "SPY": "标普500"}
                else:
                    return AnalysisResult(
                        request_id=request_id,
                        intent=intent,
                        mode=mode,
                        success=False,
                        error_code=ErrorCode.INVALID_INPUT,
                        error_message="资产对比需要至少两个股票代码",
                        needs_clarification=True,
                        clarify_question=ClarifyQuestion(
                            question="请提供要对比的股票代码（至少两个）",
                            field_name="tickers",
                            reason="资产对比需要至少两个股票代码",
                        ),
                    )
            else:
                # 转换为字典格式
                if isinstance(tickers, list):
                    tickers = {t: t for t in tickers}

            return use_case.execute(
                tickers=tickers,
                request_id=request_id,
                mode=mode,
            )

        elif intent == Intent.MARKET_SENTIMENT:
            return use_case.execute(
                request_id=request_id,
                mode=mode,
            )

        elif intent == Intent.MACRO_EVENTS:
            days_ahead = params.get("days_ahead", 30)
            return use_case.execute(
                days_ahead=days_ahead,
                request_id=request_id,
                mode=mode,
            )

        else:
            # 默认执行
            return use_case.execute(
                request_id=request_id,
                mode=mode,
            )

    def _create_error_result(
        self,
        request_id: str,
        intent: Intent,
        mode: ResponseMode,
        error_code: ErrorCode,
        error_message: str,
        start_time: float,
    ) -> AnalysisResult:
        """创建错误结果"""
        return AnalysisResult(
            request_id=request_id,
            intent=intent,
            mode=mode,
            success=False,
            error_code=error_code,
            error_message=error_message,
            latency_ms=int((time.time() - start_time) * 1000),
            timestamp=datetime.now(),
        )


# 工厂函数：便于创建 Orchestrator 实例
def create_orchestrator(
    market_data_port: MarketDataPort,
    news_port: NewsPort,
    sentiment_port: SentimentPort,
    search_port: SearchPort,
    time_port: TimePort,
    llm_port: Optional[LLMPort] = None,
) -> Orchestrator:
    """
    创建 Orchestrator 实例

    便于依赖注入和测试
    """
    return Orchestrator(
        market_data_port=market_data_port,
        news_port=news_port,
        sentiment_port=sentiment_port,
        search_port=search_port,
        time_port=time_port,
        llm_port=llm_port,
    )
