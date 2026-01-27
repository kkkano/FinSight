"""
端口接口定义 - 依赖倒置的核心

所有外部服务交互都通过这些接口进行，
具体实现由适配器层提供。

设计原则：
1. 接口隔离：每个接口只包含相关的方法
2. 依赖倒置：用例层依赖接口，不依赖具体实现
3. 异常抽象：接口定义标准异常类型
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime

from finsight.domain.models import (
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
    EconomicEvent,
    PerformanceComparison,
    DrawdownAnalysis,
    Intent,
    RouteDecision,
    AnalysisRequest,
)


# ==================== 异常定义 ====================

class PortError(Exception):
    """端口层基础异常"""
    def __init__(self, message: str, source: str = "unknown"):
        self.message = message
        self.source = source
        super().__init__(f"[{source}] {message}")


class DataUnavailableError(PortError):
    """数据不可用异常"""
    pass


class RateLimitError(PortError):
    """频率限制异常"""
    pass


class InvalidInputError(PortError):
    """输入无效异常"""
    pass


class TimeoutError(PortError):
    """超时异常"""
    pass


# ==================== 端口接口 ====================

class MarketDataPort(ABC):
    """市场数据端口 - 股票价格、公司信息等"""

    @abstractmethod
    def get_stock_price(self, ticker: str) -> StockPrice:
        """
        获取股票实时价格

        Args:
            ticker: 股票代码（如 AAPL, TSLA）

        Returns:
            StockPrice: 结构化的价格数据

        Raises:
            DataUnavailableError: 数据不可用
            InvalidInputError: 无效的股票代码
        """
        pass

    @abstractmethod
    def get_company_info(self, ticker: str) -> CompanyInfo:
        """
        获取公司基本信息

        Args:
            ticker: 股票代码

        Returns:
            CompanyInfo: 结构化的公司信息

        Raises:
            DataUnavailableError: 数据不可用
            InvalidInputError: 无效的股票代码
        """
        pass

    @abstractmethod
    def get_performance_comparison(
        self,
        tickers: Dict[str, str],
        period: str = "1y"
    ) -> PerformanceComparison:
        """
        获取多资产绩效对比

        Args:
            tickers: 资产字典 {"名称": "代码"}
            period: 时间周期

        Returns:
            PerformanceComparison: 对比结果
        """
        pass

    @abstractmethod
    def analyze_historical_drawdowns(self, ticker: str) -> DrawdownAnalysis:
        """
        分析历史回撤

        Args:
            ticker: 股票代码

        Returns:
            DrawdownAnalysis: 回撤分析结果
        """
        pass


class NewsPort(ABC):
    """新闻数据端口"""

    @abstractmethod
    def get_company_news(
        self,
        ticker: str,
        limit: int = 10
    ) -> List[NewsItem]:
        """
        获取公司相关新闻

        Args:
            ticker: 股票代码
            limit: 返回条数上限

        Returns:
            List[NewsItem]: 新闻列表
        """
        pass


class SentimentPort(ABC):
    """市场情绪端口"""

    @abstractmethod
    def get_market_sentiment(self) -> MarketSentiment:
        """
        获取市场整体情绪指标

        Returns:
            MarketSentiment: 市场情绪数据
        """
        pass


class SearchPort(ABC):
    """搜索端口"""

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        执行网络搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            List[Dict]: 搜索结果列表
        """
        pass


class EconomicDataPort(ABC):
    """经济数据端口"""

    @abstractmethod
    def get_economic_events(
        self,
        days_ahead: int = 7
    ) -> List[EconomicEvent]:
        """
        获取近期经济日历事件

        Args:
            days_ahead: 未来天数

        Returns:
            List[EconomicEvent]: 经济事件列表
        """
        pass


class TimePort(ABC):
    """时间服务端口"""

    @abstractmethod
    def get_current_datetime(self) -> datetime:
        """
        获取当前日期时间

        Returns:
            datetime: 当前时间
        """
        pass

    @abstractmethod
    def get_formatted_datetime(self, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """
        获取格式化的日期时间字符串

        Args:
            fmt: 格式字符串

        Returns:
            str: 格式化的时间字符串
        """
        pass


class LLMPort(ABC):
    """LLM 服务端口"""

    @abstractmethod
    def classify_intent(
        self,
        query: str,
        context: Optional[str] = None
    ) -> RouteDecision:
        """
        分类用户意图

        Args:
            query: 用户查询
            context: 可选的上下文信息

        Returns:
            RouteDecision: 路由决策
        """
        pass

    @abstractmethod
    def generate_report(
        self,
        data: Dict[str, Any],
        template: str,
        mode: str = "deep"
    ) -> str:
        """
        生成分析报告

        Args:
            data: 结构化数据
            template: 报告模板
            mode: 报告模式（summary/deep）

        Returns:
            str: 生成的报告文本
        """
        pass

    @abstractmethod
    def extract_entities(
        self,
        query: str
    ) -> Dict[str, Any]:
        """
        从查询中提取实体（如股票代码、时间范围等）

        Args:
            query: 用户查询

        Returns:
            Dict: 提取的实体
        """
        pass


# ==================== 复合端口（可选） ====================

class AnalysisPort(ABC):
    """
    分析端口 - 聚合多个数据源

    用于需要同时访问多个数据源的场景，
    可以由 Orchestrator 层实现。
    """

    @abstractmethod
    def collect_stock_data(
        self,
        ticker: str
    ) -> Dict[str, Any]:
        """
        收集股票相关的所有数据

        Args:
            ticker: 股票代码

        Returns:
            Dict: 聚合的数据
        """
        pass
