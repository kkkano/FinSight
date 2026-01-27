"""
系统时间适配器 - 实现 TimePort

提供系统时间服务。
"""

from datetime import datetime

from finsight.ports.interfaces import TimePort


class SystemTimeAdapter(TimePort):
    """
    系统时间适配器

    实现 TimePort 接口，提供时间相关服务。
    """

    def __init__(self, timezone: str = None):
        """
        初始化适配器

        Args:
            timezone: 时区（可选，默认使用系统时区）
        """
        self.timezone = timezone

    def get_current_datetime(self) -> datetime:
        """获取当前日期时间"""
        return datetime.now()

    def get_formatted_datetime(self, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """获取格式化的日期时间字符串"""
        return datetime.now().strftime(fmt)

    def get_date(self) -> str:
        """获取当前日期（YYYY-MM-DD）"""
        return datetime.now().strftime("%Y-%m-%d")

    def get_time(self) -> str:
        """获取当前时间（HH:MM:SS）"""
        return datetime.now().strftime("%H:%M:%S")

    def is_market_hours(self) -> bool:
        """
        判断是否在美股交易时间

        Returns:
            bool: 是否在交易时间（简化判断，未考虑节假日）
        """
        now = datetime.now()
        # 美股交易时间：东部时间 9:30 - 16:00
        # 这里简化处理，假设服务器在东部时区
        hour = now.hour
        minute = now.minute

        # 周末不交易
        if now.weekday() >= 5:
            return False

        # 简化的交易时间判断
        if hour < 9 or hour >= 16:
            return False
        if hour == 9 and minute < 30:
            return False

        return True
