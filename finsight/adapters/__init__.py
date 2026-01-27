"""
适配器层 - 端口接口的具体实现

将外部服务（yfinance, DuckDuckGo, CNN Fear & Greed 等）
适配为标准的端口接口。

包含：
- YFinanceAdapter: Yahoo Finance 市场数据适配器
- DDGSAdapter: DuckDuckGo 搜索适配器
- CNNSentimentAdapter: CNN Fear & Greed 情绪适配器
- SystemTimeAdapter: 系统时间适配器
- LiteLLMAdapter: LiteLLM 服务适配器
"""

from finsight.adapters.yfinance_adapter import YFinanceAdapter
from finsight.adapters.ddgs_adapter import DDGSAdapter
from finsight.adapters.cnn_adapter import CNNSentimentAdapter
from finsight.adapters.system_time_adapter import SystemTimeAdapter
from finsight.adapters.llm_adapter import LiteLLMAdapter

__all__ = [
    "YFinanceAdapter",
    "DDGSAdapter",
    "CNNSentimentAdapter",
    "SystemTimeAdapter",
    "LiteLLMAdapter",
]
