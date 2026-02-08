"""
能力选择器 - 根据资产类型决定前端渲染哪些 Widget

根据不同资产类型的特征，返回对应的能力集合：
- equity: 显示营收趋势、分部收入、K线图
- index: 显示行业权重、成分股排行、K线图
- etf: 显示行业权重、持仓明细、K线图
- crypto: 仅显示K线图
- portfolio: 显示持仓明细
"""
from backend.dashboard.schemas import ActiveAsset, Capabilities


def select_capabilities(asset: ActiveAsset) -> Capabilities:
    """
    根据资产类型返回仪表盘能力集。

    规则矩阵:
    ┌──────────────┬────────────┬─────────┬─────────────┬───────────┬──────────┐
    │ 能力          │ equity     │ index   │ etf         │ crypto    │ portfolio│
    ├──────────────┼────────────┼─────────┼─────────────┼───────────┼──────────┤
    │ revenue_trend │ ✅         │ ❌      │ ❌          │ ❌        │ ❌       │
    │ segment_mix   │ ✅         │ ❌      │ ❌          │ ❌        │ ❌       │
    │ sector_weights│ ❌         │ ✅      │ ✅          │ ❌        │ ❌       │
    │ top_constit.  │ ❌         │ ✅      │ ❌          │ ❌        │ ❌       │
    │ holdings      │ ❌         │ ❌      │ ✅          │ ❌        │ ✅       │
    │ market_chart  │ ✅         │ ✅      │ ✅          │ ✅        │ ❌       │
    └──────────────┴────────────┴─────────┴─────────────┴───────────┴──────────┘

    Args:
        asset: 已解析的资产对象

    Returns:
        Capabilities: 能力集合，决定前端显示哪些组件

    Examples:
        >>> from backend.dashboard.asset_resolver import resolve_asset
        >>> caps = select_capabilities(resolve_asset("AAPL"))
        >>> caps.revenue_trend
        True
        >>> caps.sector_weights
        False
    """
    t = asset.type

    return Capabilities(
        # 营收趋势：仅股票有
        revenue_trend=(t == "equity"),
        # 分部收入：仅股票有
        segment_mix=(t == "equity"),
        # 行业权重：指数和 ETF 有
        sector_weights=(t in ("index", "etf")),
        # 成分股排行：仅指数有
        top_constituents=(t == "index"),
        # 持仓明细：ETF 和投资组合有
        holdings=(t in ("etf", "portfolio")),
        # K线图：除投资组合外都有
        market_chart=(t != "portfolio"),
    )


def get_widget_order(asset_type: str) -> list[str]:
    """
    获取组件的默认显示顺序。

    Args:
        asset_type: 资产类型

    Returns:
        list[str]: 组件 ID 列表，按推荐显示顺序排列
    """
    # 基础顺序：snapshot 总是第一个
    base_order = ["snapshot"]

    if asset_type == "equity":
        return base_order + [
            "revenue_trend",
            "segment_mix",
            "market_chart",
            "news_feed",
        ]
    elif asset_type == "index":
        return base_order + [
            "sector_weights",
            "top_constituents",
            "market_chart",
            "news_feed",
        ]
    elif asset_type == "etf":
        return base_order + [
            "sector_weights",
            "holdings",
            "market_chart",
            "news_feed",
        ]
    elif asset_type == "crypto":
        return base_order + [
            "market_chart",
            "news_feed",
        ]
    elif asset_type == "portfolio":
        return base_order + [
            "holdings",
            "news_feed",
        ]
    else:
        # 未知类型，返回最小集
        return base_order + ["market_chart", "news_feed"]


def filter_hidden_widgets(
    widget_order: list[str],
    hidden_widgets: list[str],
) -> list[str]:
    """
    过滤掉隐藏的组件。

    Args:
        widget_order: 原始组件顺序
        hidden_widgets: 需要隐藏的组件 ID 列表

    Returns:
        list[str]: 过滤后的组件 ID 列表
    """
    hidden_set = set(hidden_widgets)
    return [w for w in widget_order if w not in hidden_set]
