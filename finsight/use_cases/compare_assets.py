"""
资产对比用例 - 比较多个资产的表现
"""

from typing import Optional, Dict
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
    TimePort,
    DataUnavailableError,
)
from finsight.use_cases.base import AnalysisUseCase


class CompareAssetsUseCase(AnalysisUseCase):
    """
    资产对比用例

    比较多个资产（股票、指数、加密货币等）的表现。
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        time_port: TimePort,
    ):
        self.market_data = market_data_port
        self.time = time_port

    def execute(
        self,
        tickers: Dict[str, str],
        period: str = "1y",
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.SUMMARY,
    ) -> AnalysisResult:
        """
        执行资产对比

        Args:
            tickers: 资产字典 {"名称": "代码"}
            period: 对比时间周期
            request_id: 请求ID
            mode: 响应模式

        Returns:
            AnalysisResult: 对比结果
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.COMPARE_ASSETS,
            mode=mode,
        )

        try:
            comparison = self.market_data.get_performance_comparison(tickers, period)

            result.performance_comparison = comparison
            result.tools_called.append('get_performance_comparison')
            result.evidences.append(Evidence(
                source="Yahoo Finance",
                timestamp=self.time.get_current_datetime(),
            ))

            result.report = self._generate_report(comparison)

        except DataUnavailableError as e:
            result.success = False
            result.error_code = ErrorCode.DATA_UNAVAILABLE
            result.error_message = str(e)

        except Exception as e:
            result.success = False
            result.error_code = ErrorCode.INTERNAL_ERROR
            result.error_message = f"内部错误: {str(e)}"

        return result

    def _generate_report(self, comparison) -> str:
        """生成对比报告"""
        if not comparison.assets:
            return "## 资产对比\n\n无法获取对比数据。"

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
            report += f"| {asset.name} | {asset.ticker} | {emoji} {asset.period_return:+}% |\n"

        # 添加分析
        if sorted_assets:
            best = sorted_assets[0]
            worst = sorted_assets[-1]
            report += f"\n**表现最佳:** {best.name} ({best.period_return:+}%)\n"
            report += f"**表现最差:** {worst.name} ({worst.period_return:+}%)\n"

        report += f"\n---\n*更新时间: {comparison.timestamp.strftime('%Y-%m-%d %H:%M')}*"

        return report
