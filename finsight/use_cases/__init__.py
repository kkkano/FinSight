"""
用例层 - 业务逻辑的核心实现

每个用例代表一个独立的业务场景，
只依赖 ports 接口，不依赖具体实现。

包含：
- AnalyzeStockUseCase: 深度股票分析
- GetStockPriceUseCase: 获取股票价格
- GetStockNewsUseCase: 获取股票新闻
- CompareAssetsUseCase: 资产对比分析
- GetMarketSentimentUseCase: 市场情绪分析
- GetMacroEventsUseCase: 宏观经济事件
"""

from finsight.use_cases.analyze_stock import AnalyzeStockUseCase
from finsight.use_cases.stock_price import GetStockPriceUseCase
from finsight.use_cases.stock_news import GetStockNewsUseCase
from finsight.use_cases.compare_assets import CompareAssetsUseCase
from finsight.use_cases.market_sentiment import GetMarketSentimentUseCase
from finsight.use_cases.macro_events import GetMacroEventsUseCase

__all__ = [
    "AnalyzeStockUseCase",
    "GetStockPriceUseCase",
    "GetStockNewsUseCase",
    "CompareAssetsUseCase",
    "GetMarketSentimentUseCase",
    "GetMacroEventsUseCase",
]
