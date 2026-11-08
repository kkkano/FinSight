"""仅接受来自真实用户当前消息的明确、完整操作授权。"""
from __future__ import annotations
import re


def explicitly_authorizes(query: str, action: str, ticker: str) -> bool:
    symbol = re.escape(ticker)
    prefix = r"\s*(?:请(?:帮我)?|帮我)?\s*"
    suffix = r"\s*[。！!]?\s*"
    if action == "watchlist.add":
        patterns = [
            prefix + r"(?:把|将)?\s*" + symbol + r"\s*(?:加入|添加)(?:到)?\s*(?:我的)?自选(?:股)?" + suffix,
            prefix + r"(?:加入|添加)\s*" + symbol + r"\s*(?:到)?(?:我的)?自选(?:股)?" + suffix,
            r"\s*(?:please\s+)?add\s+" + symbol + r"\s+to\s+(?:my\s+)?watchlist[.!]?\s*",
        ]
    elif action == "watchlist.remove":
        patterns = [
            prefix + r"(?:把|将)?\s*" + symbol + r"\s*从(?:我的)?自选(?:股)?(?:中)?(?:移除|删除)" + suffix,
            r"\s*(?:please\s+)?remove\s+" + symbol + r"\s+from\s+(?:my\s+)?watchlist[.!]?\s*",
        ]
    else:
        return False
    return any(re.fullmatch(pattern, query, re.IGNORECASE) for pattern in patterns)

