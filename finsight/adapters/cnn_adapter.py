"""
CNN Fear & Greed 适配器 - 实现 SentimentPort

从 CNN 获取市场恐惧与贪婪指数。
"""

from datetime import datetime
from typing import Optional

import requests

from finsight.domain.models import MarketSentiment
from finsight.ports.interfaces import (
    SentimentPort,
    DataUnavailableError,
)


class CNNSentimentAdapter(SentimentPort):
    """
    CNN Fear & Greed Index 适配器

    实现 SentimentPort 接口，获取市场情绪指标。
    """

    API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )

    def __init__(
        self,
        timeout: int = 20,
        proxy: Optional[str] = None
    ):
        """
        初始化适配器

        Args:
            timeout: 请求超时时间（秒）
            proxy: 代理服务器地址（可选）
        """
        self.timeout = timeout
        self.proxies = {'http': proxy, 'https': proxy} if proxy else {}
        self.source = "CNN Fear & Greed Index"

    def get_market_sentiment(self) -> MarketSentiment:
        """获取市场整体情绪指标"""
        try:
            headers = {'User-Agent': self.USER_AGENT}
            response = requests.get(
                self.API_URL,
                timeout=self.timeout,
                proxies=self.proxies,
                headers=headers
            )
            response.raise_for_status()

            data = response.json()
            fg_data = data.get('fear_and_greed', {})

            score = int(fg_data.get('score', 50))
            rating = fg_data.get('rating', 'Neutral')

            # 获取历史对比数据
            previous_close = fg_data.get('previous_close')
            week_ago = fg_data.get('previous_1_week')
            month_ago = fg_data.get('previous_1_month')
            year_ago = fg_data.get('previous_1_year')

            return MarketSentiment(
                fear_greed_index=score,
                label=rating,
                previous_close=int(previous_close) if previous_close else None,
                week_ago=int(week_ago) if week_ago else None,
                month_ago=int(month_ago) if month_ago else None,
                year_ago=int(year_ago) if year_ago else None,
                timestamp=datetime.now(),
                source=self.source,
            )

        except requests.exceptions.Timeout:
            raise DataUnavailableError(
                "CNN API 请求超时",
                source=self.source
            )
        except requests.exceptions.RequestException as e:
            raise DataUnavailableError(
                f"CNN API 请求失败: {str(e)}",
                source=self.source
            )
        except (KeyError, ValueError) as e:
            raise DataUnavailableError(
                f"CNN API 响应解析失败: {str(e)}",
                source=self.source
            )

    def get_sentiment_label(self, score: int) -> str:
        """
        根据分数返回情绪标签

        Args:
            score: 恐惧与贪婪指数（0-100）

        Returns:
            str: 情绪标签
        """
        if score <= 20:
            return "Extreme Fear"
        elif score <= 40:
            return "Fear"
        elif score <= 60:
            return "Neutral"
        elif score <= 80:
            return "Greed"
        else:
            return "Extreme Greed"
