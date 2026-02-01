"""
Dashboard 枚举定义

定义资产类型、时间范围、新闻模式等标准化枚举值。
"""
from enum import Enum


class AssetType(str, Enum):
    """
    资产类型枚举

    用于区分不同类型的金融资产，决定仪表盘渲染哪些组件。
    """
    EQUITY = "equity"       # 股票
    INDEX = "index"         # 指数
    ETF = "etf"             # 交易所交易基金
    CRYPTO = "crypto"       # 加密货币
    PORTFOLIO = "portfolio" # 投资组合


class TimeRange(str, Enum):
    """
    K线时间范围枚举

    用于图表数据的时间范围选择。
    """
    D1 = "1D"   # 1 天
    W1 = "1W"   # 1 周
    M1 = "1M"   # 1 月
    M3 = "3M"   # 3 月
    M6 = "6M"   # 6 月
    Y1 = "1Y"   # 1 年
    Y5 = "5Y"   # 5 年


class NewsMode(str, Enum):
    """
    新闻模式枚举

    - MARKET: 全市场新闻 7x24
    - IMPACT: 与当前资产相关的影响新闻
    - SECTOR: 行业新闻（预留）
    """
    MARKET = "market"
    IMPACT = "impact"
    SECTOR = "sector"
