"""
报告生成器 - 将分析结果转换为用户可读的报告

设计原则：
1. 模板驱动：支持多种报告模板
2. 模式感知：根据 Summary/Deep 模式生成不同详细程度
3. 多格式支持：Markdown、HTML、纯文本
4. 可扩展：支持自定义模板
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from abc import ABC, abstractmethod
from enum import Enum

from finsight.domain.models import (
    AnalysisResult,
    Intent,
    ResponseMode,
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
    EconomicEvent,
    PerformanceComparison,
)


class ReportFormat(str, Enum):
    """报告格式"""
    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"


class ReportTemplate(ABC):
    """报告模板基类"""

    @abstractmethod
    def render(
        self,
        result: AnalysisResult,
        mode: ResponseMode
    ) -> str:
        """渲染报告"""
        pass


class StockPriceTemplate(ReportTemplate):
    """股票价格报告模板"""

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        if not result.stock_price:
            return "## 股票价格\n\n暂无数据"

        price = result.stock_price
        emoji = "🟢" if price.change >= 0 else "🔴"

        report = f"## {price.ticker} 股票价格\n\n"
        report += f"**当前价格**: ${price.current_price} {emoji} {price.change_percent:+.2f}%\n\n"

        if mode == ResponseMode.DEEP:
            report += "### 详细数据\n\n"
            report += "| 指标 | 数值 |\n"
            report += "|------|------|\n"
            report += f"| 今日变动 | {emoji} ${price.change:+.2f} ({price.change_percent:+.2f}%) |\n"
            if price.high_52w:
                report += f"| 52周最高 | ${price.high_52w} |\n"
            if price.low_52w:
                report += f"| 52周最低 | ${price.low_52w} |\n"
            if price.volume:
                report += f"| 成交量 | {price.volume:,} |\n"
            if price.market_cap:
                report += f"| 市值 | ${price.market_cap:,.0f} |\n"
            if price.pe_ratio:
                report += f"| 市盈率 | {price.pe_ratio:.2f} |\n"
            if price.dividend_yield:
                report += f"| 股息率 | {price.dividend_yield:.2f}% |\n"

        report += f"\n---\n*数据来源: {price.source} | 更新时间: {price.timestamp.strftime('%Y-%m-%d %H:%M')}*"
        return report


class StockNewsTemplate(ReportTemplate):
    """股票新闻报告模板"""

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        if not result.news_items:
            return "## 最新新闻\n\n暂无新闻"

        report = "## 最新新闻\n\n"

        limit = 10 if mode == ResponseMode.DEEP else 5
        news_list = result.news_items[:limit]

        for i, news in enumerate(news_list, 1):
            date_str = news.published_at.strftime('%Y-%m-%d') if news.published_at else '未知日期'
            report += f"**{i}. [{date_str}] {news.title}**\n"

            if mode == ResponseMode.DEEP:
                if news.summary:
                    report += f"   > {news.summary[:200]}...\n" if len(news.summary) > 200 else f"   > {news.summary}\n"
                if news.publisher:
                    report += f"   来源: {news.publisher}\n"

            if news.url:
                report += f"   [阅读全文]({news.url})\n"
            report += "\n"

        report += f"---\n*共 {len(result.news_items)} 条新闻*"
        return report


class MarketSentimentTemplate(ReportTemplate):
    """市场情绪报告模板"""

    SENTIMENT_MAP = {
        'Extreme Fear': ('😱', '极度恐惧', '市场极度悲观，可能存在超卖机会'),
        'Fear': ('😨', '恐惧', '市场情绪偏悲观，保持谨慎'),
        'Neutral': ('😐', '中性', '市场情绪平稳，观望为主'),
        'Greed': ('😊', '贪婪', '市场情绪乐观，注意风险'),
        'Extreme Greed': ('🤑', '极度贪婪', '市场可能过热，警惕回调'),
    }

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        if not result.market_sentiment:
            return "## 市场情绪\n\n暂无数据"

        sentiment = result.market_sentiment
        emoji, label_cn, advice = self.SENTIMENT_MAP.get(
            sentiment.label,
            ('❓', sentiment.label, '请谨慎判断')
        )

        report = f"## 市场情绪指标\n\n"
        report += f"### CNN 恐惧与贪婪指数\n\n"
        report += f"{emoji} **{sentiment.fear_greed_index}** - {label_cn}\n\n"

        if mode == ResponseMode.DEEP:
            report += "| 时间 | 指数 |\n"
            report += "|------|------|\n"
            report += f"| 当前 | {sentiment.fear_greed_index} |\n"
            report += f"| 昨日收盘 | {sentiment.previous_close or 'N/A'} |\n"
            report += f"| 一周前 | {sentiment.week_ago or 'N/A'} |\n"
            report += f"| 一月前 | {sentiment.month_ago or 'N/A'} |\n"
            report += f"| 一年前 | {sentiment.year_ago or 'N/A'} |\n\n"

            report += "### 解读\n\n"
            report += f"{advice}\n\n"
            report += "- 指数范围: 0-100\n"
            report += "- 0-25: 极度恐惧\n"
            report += "- 25-45: 恐惧\n"
            report += "- 45-55: 中性\n"
            report += "- 55-75: 贪婪\n"
            report += "- 75-100: 极度贪婪\n"

        report += f"\n---\n*数据来源: {sentiment.source} | 更新时间: {sentiment.timestamp.strftime('%Y-%m-%d %H:%M')}*"
        return report


class CompareAssetsTemplate(ReportTemplate):
    """资产对比报告模板"""

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        if not result.performance_comparison or not result.performance_comparison.assets:
            return "## 资产对比\n\n无法获取对比数据"

        comparison = result.performance_comparison
        report = f"## 资产表现对比\n\n"
        report += f"*对比周期: {comparison.period}*\n\n"

        report += "| 资产 | 代码 | 收益率 |\n"
        report += "|------|------|--------|\n"

        # 按收益率排序
        sorted_assets = sorted(
            comparison.assets,
            key=lambda x: float(x.period_return),
            reverse=True
        )

        for asset in sorted_assets:
            emoji = "🟢" if asset.period_return >= 0 else "🔴"
            report += f"| {asset.name} | {asset.ticker} | {emoji} {asset.period_return:+.2f}% |\n"

        if mode == ResponseMode.DEEP and sorted_assets:
            best = sorted_assets[0]
            worst = sorted_assets[-1]
            report += f"\n### 分析摘要\n\n"
            report += f"- **表现最佳:** {best.name} ({best.period_return:+.2f}%)\n"
            report += f"- **表现最差:** {worst.name} ({worst.period_return:+.2f}%)\n"

            # 计算平均收益
            avg_return = sum(float(a.period_return) for a in sorted_assets) / len(sorted_assets)
            report += f"- **平均收益:** {avg_return:+.2f}%\n"

        report += f"\n---\n*更新时间: {comparison.timestamp.strftime('%Y-%m-%d %H:%M')}*"
        return report


class MacroEventsTemplate(ReportTemplate):
    """宏观经济事件报告模板"""

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        now = datetime.now()
        month_name = now.strftime('%B')
        year = now.year

        report = f"## {month_name} {year} 经济日历\n\n"

        if not result.economic_events:
            report += "暂无找到重要经济事件信息。\n"
            report += "\n建议访问以下网站获取最新经济日历:\n"
            report += "- [Investing.com 经济日历](https://www.investing.com/economic-calendar/)\n"
            report += "- [ForexFactory](https://www.forexfactory.com/calendar)\n"
            return report

        # 按影响程度分组
        high_impact = [e for e in result.economic_events if e.impact == "high"]
        medium_impact = [e for e in result.economic_events if e.impact == "medium"]
        low_impact = [e for e in result.economic_events if e.impact == "low"]

        if high_impact:
            report += "### 🔴 高影响事件\n\n"
            for event in high_impact:
                report += f"- **{event.event}** ({event.date})\n"

        if medium_impact:
            report += "\n### 🟡 中影响事件\n\n"
            for event in medium_impact:
                report += f"- {event.event} ({event.date})\n"

        if mode == ResponseMode.DEEP and low_impact:
            report += "\n### 🟢 低影响事件\n\n"
            for event in low_impact:
                report += f"- {event.event} ({event.date})\n"

        report += "\n### 重要提示\n\n"
        report += "- FOMC 会议和利率决议通常对市场影响最大\n"
        report += "- CPI/PPI 数据影响通胀预期和货币政策\n"
        report += "- 非农就业数据是劳动力市场的关键指标\n"

        report += f"\n---\n*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        return report


class StockAnalysisTemplate(ReportTemplate):
    """综合股票分析报告模板"""

    def render(self, result: AnalysisResult, mode: ResponseMode) -> str:
        # 如果已有 LLM 生成的报告，直接使用
        if result.report:
            return result.report

        # 否则组合各部分生成报告
        ticker = result.stock_price.ticker if result.stock_price else "Unknown"
        report = f"# {ticker} 投资分析报告\n\n"
        report += f"*报告日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"

        # 价格部分
        if result.stock_price:
            price_template = StockPriceTemplate()
            report += price_template.render(result, mode) + "\n\n"

        # 公司信息
        if result.company_info:
            report += "## 公司概况\n\n"
            info = result.company_info
            report += f"- **名称**: {info.name}\n"
            if info.sector:
                report += f"- **行业**: {info.sector}"
                if info.industry:
                    report += f" / {info.industry}"
                report += "\n"
            if mode == ResponseMode.DEEP and info.description:
                desc = info.description[:500] + "..." if len(info.description) > 500 else info.description
                report += f"\n{desc}\n"
            report += "\n"

        # 新闻部分
        if result.news_items:
            news_template = StockNewsTemplate()
            report += news_template.render(result, mode) + "\n\n"

        # 市场情绪
        if result.market_sentiment:
            sentiment_template = MarketSentimentTemplate()
            report += sentiment_template.render(result, mode) + "\n\n"

        # 工具调用记录
        if mode == ResponseMode.DEEP and result.tools_called:
            report += "## 数据来源\n\n"
            report += f"本报告使用了以下数据接口: {', '.join(result.tools_called)}\n\n"

        report += "---\n*此报告由 FinSight AI 自动生成*"
        return report


class ReportWriter:
    """
    报告生成器

    职责：
    1. 根据分析结果生成报告
    2. 支持多种模板和格式
    3. 支持 Summary/Deep 两种模式
    """

    def __init__(self):
        """初始化报告生成器"""
        # 模板映射
        self._templates: Dict[Intent, ReportTemplate] = {
            Intent.STOCK_PRICE: StockPriceTemplate(),
            Intent.STOCK_NEWS: StockNewsTemplate(),
            Intent.STOCK_ANALYSIS: StockAnalysisTemplate(),
            Intent.COMPANY_INFO: StockAnalysisTemplate(),
            Intent.COMPARE_ASSETS: CompareAssetsTemplate(),
            Intent.MARKET_SENTIMENT: MarketSentimentTemplate(),
            Intent.MACRO_EVENTS: MacroEventsTemplate(),
        }

    def generate(
        self,
        result: AnalysisResult,
        format: ReportFormat = ReportFormat.MARKDOWN
    ) -> str:
        """
        生成报告

        Args:
            result: 分析结果
            format: 报告格式

        Returns:
            str: 生成的报告
        """
        # 获取对应模板
        template = self._templates.get(result.intent)

        if not template:
            # 默认使用股票分析模板
            template = StockAnalysisTemplate()

        # 渲染报告
        markdown_report = template.render(result, result.mode)

        # 格式转换
        if format == ReportFormat.MARKDOWN:
            return markdown_report
        elif format == ReportFormat.HTML:
            return self._markdown_to_html(markdown_report)
        elif format == ReportFormat.TEXT:
            return self._markdown_to_text(markdown_report)
        else:
            return markdown_report

    def _markdown_to_html(self, markdown: str) -> str:
        """将 Markdown 转换为 HTML"""
        # 简单转换，实际项目中可使用 markdown 库
        html = markdown
        # 标题转换
        html = html.replace("### ", "<h3>").replace("\n", "</h3>\n", 1)
        html = html.replace("## ", "<h2>").replace("\n", "</h2>\n", 1)
        html = html.replace("# ", "<h1>").replace("\n", "</h1>\n", 1)
        # 加粗
        import re
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        # 斜体
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        # 链接
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
        # 换行
        html = html.replace("\n", "<br>\n")
        return f"<div class='report'>{html}</div>"

    def _markdown_to_text(self, markdown: str) -> str:
        """将 Markdown 转换为纯文本"""
        import re
        text = markdown
        # 移除 Markdown 语法
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\|.+\|', '', text)
        text = re.sub(r'-{3,}', '---', text)
        return text

    def register_template(self, intent: Intent, template: ReportTemplate):
        """
        注册自定义模板

        Args:
            intent: 意图
            template: 模板实例
        """
        self._templates[intent] = template


# 便捷函数
def create_report_writer() -> ReportWriter:
    """创建报告生成器实例"""
    return ReportWriter()
