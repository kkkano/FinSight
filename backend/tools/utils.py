from datetime import datetime
import re
from typing import Any, Optional

def _normalize_published_date(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value).strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(value, str):
        cleaned = value.strip()
        if "T" in cleaned:
            cleaned = cleaned.split("T")[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
            return cleaned
    return None



def get_current_datetime() -> str:
    """返回当前日期和时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
