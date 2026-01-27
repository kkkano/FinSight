"""
宏观经济事件用例 - 获取经济日历
"""

from typing import Optional, List
import uuid
import re
from datetime import datetime

from finsight.domain.models import (
    AnalysisResult,
    Intent,
    ResponseMode,
    ErrorCode,
    Evidence,
    EconomicEvent,
)
from finsight.ports.interfaces import (
    SearchPort,
    TimePort,
    DataUnavailableError,
)
from finsight.use_cases.base import AnalysisUseCase


class GetMacroEventsUseCase(AnalysisUseCase):
    """
    宏观经济事件用例

    获取近期的重要经济事件和数据发布日程。
    """

    # 重要经济事件关键词
    KEY_EVENTS = [
        'FOMC', 'Fed', 'Interest Rate', 'CPI', 'PPI',
        'Jobs Report', 'Non-Farm Payrolls', 'NFP',
        'Unemployment Rate', 'GDP', 'Retail Sales',
        'PCE', 'Consumer Confidence', 'ISM',
    ]

    def __init__(
        self,
        search_port: SearchPort,
        time_port: TimePort,
    ):
        self.search = search_port
        self.time = time_port

    def execute(
        self,
        days_ahead: int = 30,
        request_id: Optional[str] = None,
        mode: ResponseMode = ResponseMode.SUMMARY,
    ) -> AnalysisResult:
        """
        执行获取宏观经济事件

        Args:
            days_ahead: 未来天数
            request_id: 请求ID
            mode: 响应模式

        Returns:
            AnalysisResult: 经济事件列表
        """
        result = AnalysisResult(
            request_id=request_id or str(uuid.uuid4()),
            intent=Intent.MACRO_EVENTS,
            mode=mode,
        )

        try:
            now = datetime.now()
            month_name = now.strftime('%B')
            year = now.year

            # 搜索经济日历
            query = f"US economic calendar {month_name} {year} FOMC CPI GDP"
            search_results = self.search.search(query, max_results=10)

            result.tools_called.append('search')

            # 解析事件
            events = self._parse_events(search_results, month_name, year)
            result.economic_events = events

            result.evidences.append(Evidence(
                source="Web Search",
                timestamp=self.time.get_current_datetime(),
            ))

            result.report = self._generate_report(events, month_name, year)

        except DataUnavailableError as e:
            result.success = False
            result.error_code = ErrorCode.DATA_UNAVAILABLE
            result.error_message = str(e)

        except Exception as e:
            result.success = False
            result.error_code = ErrorCode.INTERNAL_ERROR
            result.error_message = f"内部错误: {str(e)}"

        return result

    def _parse_events(
        self,
        search_results: List[dict],
        month: str,
        year: int
    ) -> List[EconomicEvent]:
        """从搜索结果中解析经济事件"""
        events = []
        seen = set()

        # 合并所有搜索结果文本
        all_text = " ".join([
            r.get('title', '') + ' ' + r.get('body', '')
            for r in search_results
        ])

        # 匹配事件模式
        for event_name in self.KEY_EVENTS:
            # 尝试匹配日期和事件
            patterns = [
                rf'({month}\s+\d{{1,2}})[^\n]*?({event_name})',
                rf'({event_name})[^\n]*?({month}\s+\d{{1,2}})',
                rf'(\d{{1,2}}\s+{month})[^\n]*?({event_name})',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, all_text, re.IGNORECASE)
                for match in matches:
                    # 标准化事件标识
                    event_key = event_name.lower()
                    if event_key not in seen:
                        seen.add(event_key)
                        events.append(EconomicEvent(
                            date=f"{month} {year}",
                            event=event_name,
                            country="US",
                            impact="high" if event_name in ['FOMC', 'CPI', 'NFP', 'GDP'] else "medium",
                        ))
                        break

        return events

    def _generate_report(
        self,
        events: List[EconomicEvent],
        month: str,
        year: int
    ) -> str:
        """生成经济日历报告"""
        report = f"## {month} {year} 经济日历\n\n"

        if not events:
            report += "暂无找到重要经济事件信息。\n"
            report += "\n建议访问以下网站获取最新经济日历:\n"
            report += "- [Investing.com 经济日历](https://www.investing.com/economic-calendar/)\n"
            report += "- [ForexFactory](https://www.forexfactory.com/calendar)\n"
            return report

        # 按影响程度分组
        high_impact = [e for e in events if e.impact == "high"]
        medium_impact = [e for e in events if e.impact == "medium"]

        if high_impact:
            report += "### 🔴 高影响事件\n\n"
            for event in high_impact:
                report += f"- **{event.event}**\n"

        if medium_impact:
            report += "\n### 🟡 中影响事件\n\n"
            for event in medium_impact:
                report += f"- {event.event}\n"

        report += "\n### 重要提示\n\n"
        report += "- FOMC 会议和利率决议通常对市场影响最大\n"
        report += "- CPI/PPI 数据影响通胀预期和货币政策\n"
        report += "- 非农就业数据是劳动力市场的关键指标\n"

        report += f"\n---\n*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"

        return report
