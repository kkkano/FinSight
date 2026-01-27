"""
表现层 - 报告生成与格式化

负责将结构化的分析结果转换为用户可读的报告格式。
LLM 仅在这一层使用，用于文字润色和格式化。

包含：
- ReportWriter: 报告生成器
- ReportFormat: 报告格式枚举
- ReportTemplate: 报告模板基类
- 各种具体模板实现
"""

from finsight.presentation.report_writer import (
    ReportWriter,
    ReportFormat,
    ReportTemplate,
    StockPriceTemplate,
    StockNewsTemplate,
    MarketSentimentTemplate,
    CompareAssetsTemplate,
    MacroEventsTemplate,
    StockAnalysisTemplate,
    create_report_writer,
)

__all__ = [
    "ReportWriter",
    "ReportFormat",
    "ReportTemplate",
    "StockPriceTemplate",
    "StockNewsTemplate",
    "MarketSentimentTemplate",
    "CompareAssetsTemplate",
    "MacroEventsTemplate",
    "StockAnalysisTemplate",
    "create_report_writer",
]
