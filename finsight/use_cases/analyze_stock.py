"""
深度股票分析用例 - 综合分析股票
"""

from typing import Optional, Dict, Any
import uuid

from finsight.domain.models import (
    AnalysisResult,
    Intent,
    ResponseMode,
    ErrorCode,
    Evidence,
)
from finsight.ports.interfaces import (
    MarketDataPort,
    NewsPort,
    SentimentPort,
    SearchPort,
    TimePort,
    LLMPort,
    DataUnavailableError,
)
from finsight.use_cases.base import AnalysisUseCase


class AnalyzeStockUseCase(AnalysisUseCase):
    """
    深度股票分析用例

    综合价格、公司信息、新闻、市场情绪等多维度数据，
    生成专业的投资分析报告。
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        news_port: NewsPort,
        sentiment_port: SentimentPort,
        search_port: SearchPort,
        time_port: TimePort,
        llm_port: LLMPort,
    ):
        self.market_data = market_data_port
        self.news = news_port
        self.sentiment = sentiment_port
        self.search = search_port
        self.time = time_port
        self.llm = llm_port

    def execute(
        self,
        ticker: str,
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.DEEP,
    ) -> AnalysisResult:
        """
        执行深度股票分析

        Args:
            ticker: 股票代码
            request_id: 请求ID
            mode: 响应模式（summary/deep）

        Returns:
            AnalysisResult: 完整的分析结果
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.STOCK_ANALYSIS,
            mode=mode,
        )

        collected_data: Dict[str, Any] = {
            'ticker': ticker,
            'analysis_date': self.time.get_formatted_datetime(),
        }

        # 1. 获取股票价格
        try:
            price_data = self.market_data.get_stock_price(ticker)
            result.stock_price = price_data
            result.tools_called.append('get_stock_price')
            collected_data['price'] = {
                'current': str(price_data.current_price),
                'change': str(price_data.change),
                'change_percent': str(price_data.change_percent),
                'high_52w': str(price_data.high_52w) if price_data.high_52w else None,
                'low_52w': str(price_data.low_52w) if price_data.low_52w else None,
                'pe_ratio': str(price_data.pe_ratio) if price_data.pe_ratio else None,
            }
            result.evidences.append(Evidence(
                source=price_data.source,
                timestamp=price_data.timestamp,
            ))
        except DataUnavailableError as e:
            collected_data['price_error'] = str(e)

        # 2. 获取公司信息
        try:
            company_info = self.market_data.get_company_info(ticker)
            result.company_info = company_info
            result.tools_called.append('get_company_info')
            collected_data['company'] = {
                'name': company_info.name,
                'sector': company_info.sector,
                'industry': company_info.industry,
                'description': company_info.description,
            }
        except DataUnavailableError as e:
            collected_data['company_error'] = str(e)

        # 3. 获取新闻
        try:
            news_items = self.news.get_company_news(ticker, limit=5)
            result.news_items = news_items
            result.tools_called.append('get_company_news')
            collected_data['news'] = [
                {
                    'title': n.title,
                    'date': n.published_at.strftime('%Y-%m-%d') if n.published_at else None,
                    'publisher': n.publisher,
                }
                for n in news_items
            ]
        except DataUnavailableError as e:
            collected_data['news_error'] = str(e)

        # 4. 获取市场情绪
        try:
            sentiment = self.sentiment.get_market_sentiment()
            result.market_sentiment = sentiment
            result.tools_called.append('get_market_sentiment')
            collected_data['market_sentiment'] = {
                'fear_greed_index': sentiment.fear_greed_index,
                'label': sentiment.label,
            }
        except DataUnavailableError as e:
            collected_data['sentiment_error'] = str(e)

        # 5. 使用 LLM 生成报告
        try:
            report = self.llm.generate_report(
                data=collected_data,
                template="stock_analysis",
                mode=mode.value,
            )
            result.report = report
            result.tools_called.append('generate_report')
        except Exception as e:
            # 如果 LLM 失败，生成基础报告
            result.report = self._generate_fallback_report(collected_data, mode)

        return result

    def _generate_fallback_report(self, data: Dict[str, Any], mode: ResponseMode) -> str:
        """生成备用报告（LLM 不可用时）"""
        ticker = data.get('ticker', 'Unknown')
        date = data.get('analysis_date', '')

        report = f"# {ticker} 投资分析报告\n\n"
        report += f"*报告日期: {date}*\n\n"

        # 价格部分
        if 'price' in data:
            price = data['price']
            report += "## 当前价格\n\n"
            report += f"- 当前价格: ${price.get('current', 'N/A')}\n"
            report += f"- 今日变动: {price.get('change_percent', 'N/A')}%\n"
            report += f"- 52周区间: ${price.get('low_52w', 'N/A')} - ${price.get('high_52w', 'N/A')}\n\n"

        # 公司信息
        if 'company' in data:
            company = data['company']
            report += "## 公司概况\n\n"
            report += f"- 名称: {company.get('name', 'N/A')}\n"
            report += f"- 行业: {company.get('sector', 'N/A')} / {company.get('industry', 'N/A')}\n\n"

        # 新闻
        if 'news' in data and data['news']:
            report += "## 最新动态\n\n"
            for news in data['news'][:3]:
                report += f"- [{news.get('date', '')}] {news.get('title', '')}\n"
            report += "\n"

        # 市场情绪
        if 'market_sentiment' in data:
            sentiment = data['market_sentiment']
            report += "## 市场情绪\n\n"
            report += f"恐惧与贪婪指数: {sentiment.get('fear_greed_index', 'N/A')} ({sentiment.get('label', '')})\n\n"

        report += "---\n*此为自动生成的基础报告*"

        return report
