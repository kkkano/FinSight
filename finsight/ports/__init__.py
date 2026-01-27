"""
端口层 - 定义与外部世界交互的接口

遵循依赖倒置原则，用例层只依赖这些抽象接口，
具体实现由适配器层提供。

包含：
- MarketDataPort: 市场数据接口
- NewsPort: 新闻数据接口
- SentimentPort: 情绪分析接口
- SearchPort: 搜索接口
- TimePort: 时间服务接口
- LLMPort: LLM 服务接口
"""

from finsight.ports.interfaces import (
    MarketDataPort,
    NewsPort,
    SentimentPort,
    SearchPort,
    TimePort,
    LLMPort,
    EconomicDataPort,
)

__all__ = [
    "MarketDataPort",
    "NewsPort",
    "SentimentPort",
    "SearchPort",
    "TimePort",
    "LLMPort",
    "EconomicDataPort",
]
