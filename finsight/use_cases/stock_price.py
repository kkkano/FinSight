"""
股票价格用例 - 获取股票实时价格
"""

from typing import Optional
import uuid

from finsight.domain.models import (
    AnalysisResult,
    AnalysisRequest,
    Intent,
    ResponseMode,
    ErrorCode,
    Evidence,
)
from finsight.ports.interfaces import (
    MarketDataPort,
    TimePort,
    DataUnavailableError,
    InvalidInputError,
)
from finsight.use_cases.base import AnalysisUseCase


class GetStockPriceUseCase(AnalysisUseCase):
    """
    获取股票价格用例

    输入：股票代码
    输出：结构化的价格数据
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        time_port: TimePort,
    ):
        """
        初始化用例

        Args:
            market_data_port: 市场数据端口
            time_port: 时间服务端口
        """
        self.market_data = market_data_port
        self.time = time_port

    def execute(
        self,
        ticker: str,
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.SUMMARY,
    ) -> AnalysisResult:
        """
        执行获取股票价格

        Args:
            ticker: 股票代码
            request_id: 请求ID（可选）
            mode: 响应模式

        Returns:
            AnalysisResult: 包含价格数据的分析结果
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.STOCK_PRICE,
            mode=mode,
        )

        try:
            # 获取价格数据
            price_data = self.market_data.get_stock_price(ticker)

            result.stock_price = price_data
            result.tools_called.append('get_stock_price')
            result.evidences.append(Evidence(
                source=price_data.source,
                timestamp=price_data.timestamp,
            ))

            # 生成简单报告
            result.report = self._generate_report(price_data)

        except InvalidInputError as e:
            result.success = False
            result.error_code = ErrorCode.INVALID_INPUT
            result.error_message = str(e)

        except DataUnavailableError as e:
            result.success = False
            result.error_code = ErrorCode.DATA_UNAVAILABLE
            result.error_message = str(e)

        except Exception as e:
            result.success = False
            result.error_code = ErrorCode.INTERNAL_ERROR
            result.error_message = f"内部错误: {str(e)}"

        return result

    def _generate_report(self, price_data) -> str:
        """生成价格报告"""
        change_emoji = "📈" if price_data.change >= 0 else "📉"

        report = f"""## {price_data.ticker} 股票价格

**当前价格:** ${price_data.current_price} {change_emoji}

**今日变动:** ${price_data.change} ({price_data.change_percent:+}%)

| 指标 | 数值 |
|------|------|
| 52周最高 | ${price_data.high_52w or 'N/A'} |
| 52周最低 | ${price_data.low_52w or 'N/A'} |
| 市值 | ${price_data.market_cap:,.0f} |
| 市盈率 | {price_data.pe_ratio or 'N/A'} |

---
*数据来源: {price_data.source} | 更新时间: {price_data.timestamp.strftime('%Y-%m-%d %H:%M')}*
"""
        return report
