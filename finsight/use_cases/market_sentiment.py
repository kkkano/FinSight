"""
市场情绪用例 - 获取市场整体情绪
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
    SentimentPort,
    TimePort,
    DataUnavailableError,
)
from finsight.use_cases.base import AnalysisUseCase


class GetMarketSentimentUseCase(AnalysisUseCase):
    """
    市场情绪用例

    获取 CNN Fear & Greed Index 等市场情绪指标。
    """

    def __init__(
        self,
        sentiment_port: SentimentPort,
        time_port: TimePort,
    ):
        self.sentiment = sentiment_port
        self.time = time_port

    def execute(
        self,
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.SUMMARY,
    ) -> AnalysisResult:
        """
        执行获取市场情绪

        Args:
            request_id: 请求ID
            mode: 响应模式

        Returns:
            AnalysisResult: 市场情绪数据
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.MARKET_SENTIMENT,
            mode=mode,
        )

        try:
            sentiment = self.sentiment.get_market_sentiment()

            result.market_sentiment = sentiment
            result.tools_called.append('get_market_sentiment')
            result.evidences.append(Evidence(
                source=sentiment.source,
                timestamp=sentiment.timestamp,
            ))

            result.report = self._generate_report(sentiment)

        except DataUnavailableError as e:
            result.success = False
            result.error_code = ErrorCode.DATA_UNAVAILABLE
            result.error_message = str(e)

        except Exception as e:
            result.success = False
            result.error_code = ErrorCode.INTERNAL_ERROR
            result.error_message = f"内部错误: {str(e)}"

        return result

    def _generate_report(self, sentiment) -> str:
        """生成情绪报告"""
        # 情绪等级对应的 emoji 和颜色
        sentiment_map = {
            'Extreme Fear': ('😱', '极度恐惧', '市场极度悲观，可能存在超卖机会'),
            'Fear': ('😨', '恐惧', '市场情绪偏悲观，保持谨慎'),
            'Neutral': ('😐', '中性', '市场情绪平稳，观望为主'),
            'Greed': ('😊', '贪婪', '市场情绪乐观，注意风险'),
            'Extreme Greed': ('🤑', '极度贪婪', '市场可能过热，警惕回调'),
        }

        emoji, label_cn, advice = sentiment_map.get(
            sentiment.label,
            ('❓', sentiment.label, '请谨慎判断')
        )

        report = f"""## 市场情绪指标

### CNN 恐惧与贪婪指数

{emoji} **{sentiment.fear_greed_index}** - {label_cn}

| 时间 | 指数 |
|------|------|
| 当前 | {sentiment.fear_greed_index} |
| 昨日收盘 | {sentiment.previous_close or 'N/A'} |
| 一周前 | {sentiment.week_ago or 'N/A'} |
| 一月前 | {sentiment.month_ago or 'N/A'} |
| 一年前 | {sentiment.year_ago or 'N/A'} |

### 解读

{advice}

- 指数范围: 0-100
- 0-25: 极度恐惧
- 25-45: 恐惧
- 45-55: 中性
- 55-75: 贪婪
- 75-100: 极度贪婪

---
*数据来源: {sentiment.source} | 更新时间: {sentiment.timestamp.strftime('%Y-%m-%d %H:%M')}*
"""
        return report
