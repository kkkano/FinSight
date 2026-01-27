"""
股票新闻用例 - 获取股票相关新闻
"""

from typing import Optional
import uuid

from finsight.domain.models import (
    AnalysisResult,
    Intent,
    ResponseMode,
    ErrorCode,
    Evidence,
)
from finsight.ports.interfaces import (
    NewsPort,
    TimePort,
    DataUnavailableError,
)
from finsight.use_cases.base import AnalysisUseCase


class GetStockNewsUseCase(AnalysisUseCase):
    """
    获取股票新闻用例

    输入：股票代码
    输出：相关新闻列表
    """

    def __init__(
        self,
        news_port: NewsPort,
        time_port: TimePort,
    ):
        self.news = news_port
        self.time = time_port

    def execute(
        self,
        ticker: str,
        limit: int = 10,
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.SUMMARY,
    ) -> AnalysisResult:
        """
        执行获取股票新闻

        Args:
            ticker: 股票代码
            limit: 返回条数上限
            request_id: 请求ID
            mode: 响应模式

        Returns:
            AnalysisResult: 包含新闻数据的分析结果
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.STOCK_NEWS,
            mode=mode,
        )

        try:
            news_items = self.news.get_company_news(ticker, limit)

            result.news_items = news_items
            result.tools_called.append('get_company_news')

            if news_items:
                result.evidences.append(Evidence(
                    source="Yahoo Finance",
                    timestamp=self.time.get_current_datetime(),
                ))

            result.report = self._generate_report(ticker, news_items)

        except DataUnavailableError as e:
            result.success = False
            result.error_code = ErrorCode.DATA_UNAVAILABLE
            result.error_message = str(e)

        except Exception as e:
            result.success = False
            result.error_code = ErrorCode.INTERNAL_ERROR
            result.error_message = f"内部错误: {str(e)}"

        return result

    def _generate_report(self, ticker: str, news_items) -> str:
        """生成新闻报告"""
        if not news_items:
            return f"## {ticker} 最新新闻\n\n暂无最近的新闻。"

        report = f"## {ticker} 最新新闻\n\n"

        for i, news in enumerate(news_items, 1):
            date_str = news.published_at.strftime('%Y-%m-%d') if news.published_at else '未知日期'
            report += f"**{i}. [{date_str}] {news.title}**\n"
            if news.publisher:
                report += f"   来源: {news.publisher}\n"
            if news.url:
                report += f"   [阅读全文]({news.url})\n"
            report += "\n"

        report += f"\n---\n*共 {len(news_items)} 条新闻*"
        return report
