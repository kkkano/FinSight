"""
YFinance 适配器 - 实现 MarketDataPort 和 NewsPort

从 Yahoo Finance 获取股票价格、公司信息、新闻和历史数据。
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import yfinance as yf

from finsight.domain.models import (
    StockPrice,
    CompanyInfo,
    NewsItem,
    PerformanceComparison,
    PerformanceMetric,
    DrawdownAnalysis,
)
from finsight.ports.interfaces import (
    MarketDataPort,
    NewsPort,
    DataUnavailableError,
    InvalidInputError,
    TimeoutError,
)


class YFinanceAdapter(MarketDataPort, NewsPort):
    """
    Yahoo Finance 数据适配器

    实现 MarketDataPort 和 NewsPort 接口，
    将 yfinance 的数据转换为领域模型。
    """

    def __init__(self, timeout: int = 30, rate_limit_delay: float = 1.0):
        """
        初始化适配器

        Args:
            timeout: 请求超时时间（秒）
            rate_limit_delay: 请求间隔（秒），避免频率限制
        """
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.source = "Yahoo Finance"

    def _get_ticker(self, ticker_symbol: str) -> yf.Ticker:
        """获取 yfinance Ticker 对象"""
        return yf.Ticker(ticker_symbol)

    def get_stock_price(self, ticker: str) -> StockPrice:
        """获取股票实时价格"""
        try:
            stock = self._get_ticker(ticker)
            info = stock.info

            # 尝试多种键获取当前价格
            current_price = (
                info.get('currentPrice')
                or info.get('regularMarketPrice')
                or info.get('bid')
            )

            if not current_price:
                # 从历史数据获取
                hist = stock.history(period="5d")
                if hist.empty:
                    raise DataUnavailableError(
                        f"无法获取 {ticker} 的价格数据",
                        source=self.source
                    )
                current_price = float(hist['Close'].iloc[-1])

            prev_close = info.get('previousClose', current_price)
            change = current_price - prev_close
            change_percent = (change / prev_close) * 100 if prev_close else 0

            return StockPrice(
                ticker=ticker.upper(),
                current_price=Decimal(str(round(current_price, 2))),
                change=Decimal(str(round(change, 2))),
                change_percent=Decimal(str(round(change_percent, 2))),
                currency=info.get('currency', 'USD'),
                high_52w=Decimal(str(info.get('fiftyTwoWeekHigh', 0))) if info.get('fiftyTwoWeekHigh') else None,
                low_52w=Decimal(str(info.get('fiftyTwoWeekLow', 0))) if info.get('fiftyTwoWeekLow') else None,
                volume=info.get('volume'),
                market_cap=Decimal(str(info.get('marketCap', 0))) if info.get('marketCap') else None,
                pe_ratio=Decimal(str(round(info.get('trailingPE', 0), 2))) if info.get('trailingPE') else None,
                dividend_yield=Decimal(str(round(info.get('dividendYield', 0) * 100, 2))) if info.get('dividendYield') else None,
                timestamp=datetime.now(),
                source=self.source,
            )

        except DataUnavailableError:
            raise
        except Exception as e:
            raise DataUnavailableError(
                f"获取 {ticker} 价格失败: {str(e)}",
                source=self.source
            )

    def get_company_info(self, ticker: str) -> CompanyInfo:
        """获取公司基本信息"""
        try:
            stock = self._get_ticker(ticker)
            info = stock.info

            if not info or 'longName' not in info:
                raise InvalidInputError(
                    f"无效的股票代码: {ticker}",
                    source=self.source
                )

            summary = info.get('longBusinessSummary', '')
            description = (summary[:500] + '...') if summary and len(summary) > 500 else summary

            return CompanyInfo(
                ticker=ticker.upper(),
                name=info.get('longName', '未知'),
                sector=info.get('sector'),
                industry=info.get('industry'),
                description=description or None,
                website=info.get('website'),
                employees=info.get('fullTimeEmployees'),
                headquarters=f"{info.get('city', '')}, {info.get('country', '')}".strip(', ') or None,
                ceo=None,  # yfinance 不直接提供 CEO 信息
                founded=None,
                timestamp=datetime.now(),
                source=self.source,
            )

        except (DataUnavailableError, InvalidInputError):
            raise
        except Exception as e:
            raise DataUnavailableError(
                f"获取 {ticker} 公司信息失败: {str(e)}",
                source=self.source
            )

    def get_company_news(self, ticker: str, limit: int = 10) -> List[NewsItem]:
        """获取公司相关新闻"""
        try:
            stock = self._get_ticker(ticker)
            news = stock.news

            if not news:
                return []

            # 过滤最近90天的新闻
            now = datetime.now().timestamp()
            ninety_days_ago = now - 90 * 24 * 3600

            news_items = []
            for article in news[:limit]:
                pub_time = article.get('providerPublishTime', 0)
                if pub_time < ninety_days_ago:
                    continue

                news_items.append(NewsItem(
                    title=article.get('title', '无标题'),
                    summary=None,  # yfinance 新闻不提供摘要
                    url=article.get('link'),
                    publisher=article.get('publisher'),
                    published_at=datetime.fromtimestamp(pub_time) if pub_time else None,
                    sentiment=None,
                    relevance_score=None,
                ))

            return news_items

        except Exception as e:
            raise DataUnavailableError(
                f"获取 {ticker} 新闻失败: {str(e)}",
                source=self.source
            )

    def get_performance_comparison(
        self,
        tickers: Dict[str, str],
        period: str = "1y"
    ) -> PerformanceComparison:
        """获取多资产绩效对比"""
        metrics = []

        for name, ticker in tickers.items():
            time.sleep(self.rate_limit_delay)  # 避免频率限制

            try:
                stock = self._get_ticker(ticker)
                hist = stock.history(period="2y")

                if hist.empty:
                    continue

                end_price = float(hist['Close'].iloc[-1])

                # YTD 表现
                start_of_year = datetime(datetime.now().year, 1, 1)
                ytd_hist = hist[hist.index.tz_convert(None) > start_of_year]
                if not ytd_hist.empty:
                    start_price_ytd = float(ytd_hist['Close'].iloc[0])
                    ytd_return = ((end_price - start_price_ytd) / start_price_ytd) * 100
                else:
                    ytd_return = 0

                # 1年表现
                one_year_ago = datetime.now() - timedelta(days=365)
                one_year_hist = hist[hist.index.tz_convert(None) > one_year_ago]
                if not one_year_hist.empty and len(one_year_hist) >= 2:
                    start_price_1y = float(one_year_hist['Close'].iloc[0])
                    one_year_return = ((end_price - start_price_1y) / start_price_1y) * 100
                else:
                    one_year_return = 0

                metrics.append(PerformanceMetric(
                    ticker=ticker,
                    name=name,
                    period_return=Decimal(str(round(one_year_return, 2))),
                    period="1y",
                    volatility=None,
                    sharpe_ratio=None,
                    max_drawdown=None,
                ))

            except Exception as e:
                print(f"处理 {ticker} 表现时出错: {e}")
                continue

        return PerformanceComparison(
            assets=metrics,
            benchmark=None,
            period=period,
            timestamp=datetime.now(),
        )

    def analyze_historical_drawdowns(self, ticker: str) -> DrawdownAnalysis:
        """分析历史回撤"""
        try:
            stock = self._get_ticker(ticker)
            hist = stock.history(period="10y")

            if hist.empty:
                raise DataUnavailableError(
                    f"没有 {ticker} 的历史数据",
                    source=self.source
                )

            hist['cummax'] = hist['Close'].cummax()
            hist['drawdown'] = (hist['Close'] - hist['cummax']) / hist['cummax']

            # 寻找回撤区间
            drawdowns = []
            is_in_drawdown = False
            peak_date = None

            for i in range(len(hist)):
                if hist['drawdown'].iloc[i] < 0 and not is_in_drawdown:
                    is_in_drawdown = True
                    peak_date = hist.index[i-1] if i > 0 else hist.index[i]
                elif hist['drawdown'].iloc[i] == 0 and is_in_drawdown:
                    is_in_drawdown = False
                    trough_date = hist['drawdown'].iloc[i-1:i].idxmin()
                    drawdown_percent = hist['drawdown'].loc[trough_date]
                    drawdowns.append({
                        'drawdown': float(drawdown_percent),
                        'peak_date': peak_date.strftime('%Y-%m-%d'),
                        'trough_date': trough_date.strftime('%Y-%m-%d'),
                    })

            # 取前3大回撤
            top_3 = sorted(drawdowns, key=lambda x: x['drawdown'])[:3]

            max_dd = top_3[0] if top_3 else {'drawdown': 0, 'trough_date': ''}

            return DrawdownAnalysis(
                ticker=ticker,
                max_drawdown=Decimal(str(round(max_dd['drawdown'] * 100, 2))),
                max_drawdown_date=max_dd.get('trough_date', ''),
                recovery_days=None,
                current_drawdown=Decimal(str(round(float(hist['drawdown'].iloc[-1]) * 100, 2))),
                drawdown_periods=top_3,
                timestamp=datetime.now(),
            )

        except DataUnavailableError:
            raise
        except Exception as e:
            raise DataUnavailableError(
                f"分析 {ticker} 回撤失败: {str(e)}",
                source=self.source
            )
