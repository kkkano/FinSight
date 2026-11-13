"""注册工具的唯一信封入口；保留完整数据并显式表示失败。"""
from __future__ import annotations

from functools import partial

from .catalog import TOOL_KINDS
from .normalize import adapt_result, error_result


ADAPTERS = {name: partial(adapt_result, name) for name in TOOL_KINDS}


def invoke_adapter(name, arguments, fallback):
    """报价直接消费结构化网关，其余工具使用原调用并转换协议。"""
    if name not in ADAPTERS:
        raise ValueError("tool_adapter_not_registered")
    try:
        if name in {"get_stock_price", "get_quote"}:
            from backend.services.market_data_gateway import get_market_data_gateway
            raw = get_market_data_gateway().get_quote(arguments["ticker"])
        elif name in {"get_company_info", "get_company_profile"}:
            from .sources import company_profile
            raw = company_profile(arguments)
        elif name in {"search", "web_search"}:
            from .sources import web_search
            raw = web_search(arguments)
        else:
            raw = fallback(arguments)
        return adapt_result(name, raw, arguments)
    except Exception as exc:
        return adapt_result(name, exc, arguments)


__all__ = ["ADAPTERS", "TOOL_KINDS", "adapt_result", "error_result", "invoke_adapter"]
