"""
FinSight Dashboard Module

Dashboard 核心模块，提供资产类型解析、能力选择、数据缓存等基础设施。

模块结构:
- enums.py         : 资产类型、时间范围等枚举定义
- schemas.py       : Pydantic V2 数据模型
- errors.py        : 错误码与异常定义
- asset_resolver.py: 资产类型解析器
- widget_selector.py: 仪表盘能力选择器
- cache.py         : TTL 内存缓存
"""

from backend.dashboard.enums import AssetType, TimeRange, NewsMode
from backend.dashboard.schemas import (
    ActiveAsset,
    Capabilities,
    WatchItem,
    LayoutPrefs,
    NewsModeConfig,
    DashboardState,
    DashboardData,
    MacroSnapshotData,
    DashboardResponse,
    DashboardErrorDetail,
    DashboardErrorResponse,
    SnapshotData,
    NewsItem,
    InsightCard,
    DashboardInsightsResponse,
)
from backend.dashboard.errors import (
    DashboardError,
    symbol_not_found,
    invalid_asset_type,
    data_fetch_failed,
    rate_limited,
    internal_error,
)
from backend.dashboard.asset_resolver import resolve_asset, is_valid_symbol
from backend.dashboard.widget_selector import (
    select_capabilities,
    get_widget_order,
    filter_hidden_widgets,
)
from backend.dashboard.cache import dashboard_cache

__all__ = [
    # Enums
    "AssetType",
    "TimeRange",
    "NewsMode",
    # Schemas
    "ActiveAsset",
    "Capabilities",
    "WatchItem",
    "LayoutPrefs",
    "NewsModeConfig",
    "DashboardState",
    "DashboardData",
    "MacroSnapshotData",
    "DashboardResponse",
    "DashboardErrorDetail",
    "DashboardErrorResponse",
    "SnapshotData",
    "NewsItem",
    "InsightCard",
    "DashboardInsightsResponse",
    # Errors
    "DashboardError",
    "symbol_not_found",
    "invalid_asset_type",
    "data_fetch_failed",
    "rate_limited",
    "internal_error",
    # Functions
    "resolve_asset",
    "is_valid_symbol",
    "select_capabilities",
    "get_widget_order",
    "filter_hidden_widgets",
    # Singletons
    "dashboard_cache",
]
