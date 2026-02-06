# FinSight Dashboard 实施计划 (Implementation Blueprint)

> 版本: 1.1 | 更新: 2026-02-01 | 目标: 从零落地可用仪表盘
>
> **近期更新 (v0.7.0)**:
> - **Selection Context / 上下文附件**: NewsFeed "问这条"按钮 + Selection Pill + 后端 context 注入，详见 [feature_logs/2026-02-01_selection_context.md](./feature_logs/2026-02-01_selection_context.md)

---

## 目录

- [总览](#总览)
- [文件索引表](#文件索引表)
- [Phase 0: 标准与基础设施](#phase-0-标准与基础设施)
- [Phase 1: 后端接口](#phase-1-后端接口)
- [Phase 2: 前端改造](#phase-2-前端改造)
- [Phase 3: 新闻聚合升级](#phase-3-新闻聚合升级)
- [Phase 4: 可选增强](#phase-4-可选增强)
- [Phase 5: 收尾与质量保证](#phase-5-收尾与质量保证)
- [附录 A: 一天施工建议](#附录-a-一天施工建议)
- [附录 B: 未来扩展路线](#附录-b-未来扩展路线)

---

## 总览

### 目标

将 FinSight 从"聊天 + 侧面板"模式升级为**全功能金融仪表盘**：左侧仪表盘组件（指标卡、图表、新闻）+ 右侧对话面板，支持按资产类型动态切换组件。

### 架构摘要

```
┌─────────────────────────────────────────────────────────────┐
│  /dashboard?symbol=AAPL                                     │
├──────────┬───────────────────────────────────────┬──────────┤
│ Sidebar  │       Dashboard Widgets               │  Chat    │
│ (240px)  │  ┌─────────────────────────────────┐  │  Panel   │
│          │  │ SnapshotCard (KPI 指标)          │  │ (340px)  │
│  导航菜单│  ├─────────────────────────────────┤  │          │
│          │  │                                 │  │  对话    │
│  AAPL ◀  │  │  MarketChart (K线) - C位占用     │  │  交互    │
│  TSLA    │  │       最大面积                   │  │          │
│  ^GSPC   │  ├──────────┬──────────────────────┤  │  深度    │
│  SPY     │  │ 新闻流   │ 财务/持仓数据        │  │  分析    │
│  BTC-USD │  │(NewsFeed)│(Revenue/Holdings)    │  │          │
│          │  └──────────┴──────────────────────┘  │          │
│ [+ Add]  │                                       │          │
└──────────┴───────────────────────────────────────┴──────────┘
```

**视线流设计原理：**
- **左手查阅** (List) → **中间分析** (Chart) → **右侧求证** (AI)
- K线图占据视觉C位，新闻和财务数据在底部两列排布
- 侧边栏实时关注列表支持点击快速切换标的

### 技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 前端路由 | URL query param (`?symbol=`) | 无需引入 react-router，现有代码无路由 |
| 状态管理 | Zustand (扩展现有 store) | 项目已使用 zustand@5，保持一致 |
| 图表库 | ECharts (已安装) | echarts@6 + echarts-for-react@3 已在依赖中 |
| 后端 Schema | Pydantic V2 (与现有一致) | backend/api/schemas.py 已使用 Pydantic V2 |
| 缓存策略 | 内存 dict + TTL | 与现有 orchestration/cache.py 模式一致 |
| **架构模式** | **类型驱动 (Type-Driven)** | **通过 AssetType → Capabilities → Widgets 链式映射实现差异化展示** |
| **组件决策** | **规则引擎 (非LLM)** | **金融数据结构确定，规则映射比LLM调用更高效稳定** |
| **数据入库** | **分层RAG策略** | **短期缓存(价格) + 中期存储(历史) + 长期知识库(研报)** |

#### 资产类型映射表

| 资产类型 | 判断规则 | 启用组件 | 数据来源 |
|---------|---------|----------|----------|
| `equity` | 标准股票代码 (AAPL, TSLA) | 营收趋势、分部收入、K线、新闻 | 财务API + 价格API |
| `index` | ^ 前缀 (^GSPC, ^DJI) | 行业权重、成分股、K线 | 指数成分API |
| `etf` | ETF代码识别 (SPY, QQQ) | 行业权重、持仓、K线 | ETF持仓API |
| `crypto` | -USD 后缀 (BTC-USD) | K线、新闻 | 加密货币API |

---

## 文件索引表

### 新增文件

| 文件路径 | Phase | 用途 |
|----------|-------|------|
| `backend/dashboard/__init__.py` | P0 | 包初始化 |
| `backend/dashboard/schemas.py` | P0 | Dashboard Pydantic 模型 |
| `backend/dashboard/enums.py` | P0 | 资产类型、时间范围枚举 |
| `backend/dashboard/asset_resolver.py` | P0 | 资产类型解析器 |
| `backend/dashboard/widget_selector.py` | P0 | 能力选择器 |
| `backend/dashboard/cache.py` | P1 | Dashboard 数据缓存 |
| `backend/dashboard/errors.py` | P1 | Dashboard 错误定义 |
| `backend/api/dashboard_router.py` | P1 | Dashboard API 路由 |
| `backend/news/news_service.py` | P3 | 新闻聚合服务 |
| `backend/tests/test_dashboard.py` | P5 | 后端单元测试 |
| `frontend/src/pages/Dashboard.tsx` | P2 | Dashboard 页面 |
| `frontend/src/store/dashboardStore.ts` | P2 | Dashboard 状态管理 |
| `frontend/src/hooks/useDashboardData.ts` | P2 | Dashboard 数据 hook |
| `frontend/src/components/dashboard/Watchlist.tsx` | P2 | 自选列表组件 |
| `frontend/src/components/dashboard/DashboardWidgets.tsx` | P2 | Widget 容器组件 |
| `frontend/src/components/dashboard/NewsFeed.tsx` | P2 | 新闻流组件 |
| `frontend/src/components/dashboard/LayoutSettingsModal.tsx` | P2 | 布局设置弹窗 |
| `frontend/src/components/cards/SnapshotCard.tsx` | P2 | 指标快照卡片 |
| `frontend/src/components/cards/RevenueTrendCard.tsx` | P2 | 营收趋势图 |
| `frontend/src/components/cards/SegmentMixCard.tsx` | P2 | 分部收入饼图 |
| `frontend/src/components/cards/SectorWeightsCard.tsx` | P2 | 行业权重饼图 |
| `frontend/src/components/cards/TopConstituentsCard.tsx` | P2 | 成分股排行 |
| `frontend/src/components/cards/HoldingsCard.tsx` | P2 | ETF 持仓饼图 |
| `frontend/src/components/cards/MarketChartCard.tsx` | P2 | K线/折线图 |
| `frontend/src/components/cards/MacroCard.tsx` | P2 | 宏观数据占位 |
| `frontend/src/types/dashboard.ts` | P2 | 前端 Dashboard 类型 + SelectionItem (v0.7.0) |

### v0.7.0 新增文件

| 文件路径 | Phase | 用途 |
|----------|-------|------|
| `frontend/src/utils/hash.ts` | v0.7.0 | DJB2 哈希工具（生成新闻 ID） |

### 修改文件

| 文件路径 | Phase | 修改内容 |
|----------|-------|----------|
| `backend/api/main.py` | P1 | 注册 dashboard_router |
| `frontend/src/App.tsx` | P2 | 添加 Dashboard 视图切换 |
| `frontend/src/components/Sidebar.tsx` | P2 | 添加 Dashboard 入口 |
| `frontend/src/index.css` | P2 | 添加 Dashboard 布局样式 |
| `docs/01_ARCHITECTURE.md` | P5 | 更新架构图 |
| `README.md` | P5 | 添加 Dashboard 介绍 |

---

## Phase 0: 标准与基础设施

> 🎯 目标：定义 Schema、解析器、能力选择器。建立类型驱动架构基础。

#### 核心架构决策

1. **资产类型驱动架构 (Type-Driven Architecture)**
   ```python
   # 决策流程：symbol → asset_type → capabilities → frontend_widgets
   resolve_asset("AAPL")    # → equity  → {revenue_trend: True}
   resolve_asset("^GSPC")   # → index   → {sector_weights: True}  
   resolve_asset("SPY")     # → etf     → {holdings: True}
   resolve_asset("BTC-USD") # → crypto  → {market_chart: True}
   ```

2. **图表类型映射规则 (确定性，非LLM)**
   - 时间序列数据 → 柱状图/折线图 (RevenueTrendCard)
   - 占比数据 → 饼图 (SectorWeightsCard, SegmentMixCard)  
   - OHLC数据 → K线图 (MarketChartCard)
   - 排名数据 → 表格/条形图 (TopConstituentsCard)

3. **RAG数据分层策略**
   - **短期缓存**: 内存 (价格、涨跌，TTL 5-60s)
   - **中期存储**: SQLite/PostgreSQL (K线、新闻，TTL 1-7天)  
   - **长期知识库**: 向量数据库 (财报、研报，永久存储)

### P0-1: 新增 `backend/dashboard/__init__.py`

```python
"""FinSight Dashboard Module"""
```

★ 完成标准：`import backend.dashboard` 不报错。

---

### P0-2: 新增 `backend/dashboard/enums.py`

```python
"""Dashboard 枚举定义"""
from enum import Enum


class AssetType(str, Enum):
    """资产类型"""
    EQUITY = "equity"
    INDEX = "index"
    ETF = "etf"
    CRYPTO = "crypto"
    PORTFOLIO = "portfolio"


class TimeRange(str, Enum):
    """K线时间范围"""
    D1 = "1D"
    W1 = "1W"
    M1 = "1M"
    M3 = "3M"
    M6 = "6M"
    Y1 = "1Y"
    Y5 = "5Y"


class NewsMode(str, Enum):
    """新闻模式"""
    MARKET = "market"
    IMPACT = "impact"
    SECTOR = "sector"
```

★ 完成标准：`from backend.dashboard.enums import AssetType; AssetType.EQUITY.value == "equity"` 通过。

---

### P0-3: 新增 `backend/dashboard/schemas.py`

```python
"""Dashboard Pydantic V2 Schema"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


class ActiveAsset(BaseModel):
    """当前激活资产"""
    symbol: str = Field(..., description="标准化代码")
    type: Literal["equity", "index", "etf", "crypto", "portfolio"] = Field(
        ..., description="资产类型"
    )
    display_name: str = Field(..., description="显示名称")


class Capabilities(BaseModel):
    """仪表盘能力集 - 决定前端渲染哪些组件"""
    revenue_trend: bool = Field(False, description="营收趋势图")
    segment_mix: bool = Field(False, description="分部收入饼图")
    sector_weights: bool = Field(False, description="行业权重饼图")
    top_constituents: bool = Field(False, description="成分股排行")
    holdings: bool = Field(False, description="持仓明细")
    market_chart: bool = Field(True, description="K线/折线图")


class WatchItem(BaseModel):
    """自选列表条目"""
    symbol: str = Field(..., description="代码")
    type: str = Field("equity", description="资产类型")
    name: str = Field("", description="显示名称")


class LayoutPrefs(BaseModel):
    """布局偏好"""
    hidden_widgets: List[str] = Field(default_factory=list, description="隐藏的组件 ID")
    order: List[str] = Field(default_factory=list, description="组件排序")


class NewsModeConfig(BaseModel):
    """新闻模式配置"""
    mode: Literal["market", "impact"] = Field("market", description="新闻模式")


class DashboardState(BaseModel):
    """Dashboard 完整状态"""
    active_asset: ActiveAsset
    capabilities: Capabilities
    watchlist: List[WatchItem]
    layout_prefs: LayoutPrefs
    news_mode: NewsModeConfig
    debug: Dict[str, Any] = Field(default_factory=dict)


class SnapshotData(BaseModel):
    """KPI 快照"""
    revenue: Optional[float] = None
    eps: Optional[float] = None
    gross_margin: Optional[float] = None
    fcf: Optional[float] = None
    index_level: Optional[float] = None
    nav: Optional[float] = None


class NewsItem(BaseModel):
    """新闻条目"""
    title: str
    url: str = ""
    source: str = ""
    ts: str = ""
    summary: str = ""


class DashboardData(BaseModel):
    """Dashboard 聚合数据"""
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    charts: Dict[str, Any] = Field(default_factory=dict)
    news: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)


class DashboardResponse(BaseModel):
    """Dashboard API 响应"""
    success: bool = True
    state: DashboardState
    data: DashboardData


class DashboardErrorDetail(BaseModel):
    """错误详情"""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误描述")
    details: Dict[str, Any] = Field(default_factory=dict)


class DashboardErrorResponse(BaseModel):
    """Dashboard 错误响应"""
    success: bool = False
    error: DashboardErrorDetail
```

★ 完成标准：所有模型能正确实例化，`DashboardResponse.model_json_schema()` 输出有效 JSON Schema。

---

### P0-4: 新增 `backend/dashboard/errors.py`

```python
"""Dashboard 错误码定义"""
from fastapi import HTTPException


class DashboardError:
    """错误码常量"""
    SYMBOL_NOT_FOUND = 4001
    INVALID_ASSET_TYPE = 4002
    DATA_FETCH_FAILED = 5001
    RATE_LIMITED = 4291
    INTERNAL_ERROR = 5000


def symbol_not_found(symbol: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": DashboardError.SYMBOL_NOT_FOUND,
            "message": f"Symbol '{symbol}' not found",
            "details": {"symbol": symbol},
        },
    )


def data_fetch_failed(reason: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": DashboardError.DATA_FETCH_FAILED,
            "message": f"Failed to fetch data: {reason}",
        },
    )
```

★ 完成标准：`raise symbol_not_found("INVALID")` 返回 404 + 结构化 JSON。

---

### P0-5: 新增 `backend/dashboard/asset_resolver.py`

```python
"""资产类型解析器 - 根据 symbol 判断资产类型"""
from backend.dashboard.schemas import ActiveAsset

# 常见指数映射
_INDEX_SYMBOLS = {
    "^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^FTSE", "^N225", "^HSI",
    "^STOXX50E", "000001.SS", "000300.SS", "399001.SZ", "399006.SZ",
    "SPX", "DJI", "COMP", "RUT",
}

# 常见 ETF 映射
_ETF_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "EEM",
    "GLD", "SLV", "TLT", "HYG", "IEMG", "VWO", "VEA", "VNQ",
    "ARKK", "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP",
}

# 加密货币后缀
_CRYPTO_SUFFIXES = ("-USD", "-USDT", "-BTC", "-ETH")

# 显示名称映射（部分常用）
_DISPLAY_NAMES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "NASDAQ Composite",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "000300.SS": "沪深300",
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ",
    "GLD": "SPDR Gold",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
}


def resolve_asset(symbol: str) -> ActiveAsset:
    """
    解析 symbol 返回 ActiveAsset。

    优先级：
    1. 精确匹配指数集合
    2. 精确匹配 ETF 集合
    3. 加密货币后缀
    4. 默认为 equity
    """
    upper = symbol.upper().strip()

    if upper in _INDEX_SYMBOLS or upper.startswith("^"):
        asset_type = "index"
    elif upper in _ETF_SYMBOLS:
        asset_type = "etf"
    elif any(upper.endswith(s) for s in _CRYPTO_SUFFIXES):
        asset_type = "crypto"
    else:
        asset_type = "equity"

    display_name = _DISPLAY_NAMES.get(upper, upper)

    return ActiveAsset(
        symbol=upper,
        type=asset_type,
        display_name=display_name,
    )
```

★ 完成标准：
- `resolve_asset("AAPL").type == "equity"`
- `resolve_asset("^GSPC").type == "index"`
- `resolve_asset("SPY").type == "etf"`
- `resolve_asset("BTC-USD").type == "crypto"`

---

### P0-6: 新增 `backend/dashboard/widget_selector.py`

```python
"""能力选择器 - 根据资产类型决定前端渲染哪些 Widget"""
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
    """
    t = asset.type

    return Capabilities(
        revenue_trend=(t == "equity"),
        segment_mix=(t == "equity"),
        sector_weights=(t in ("index", "etf")),
        top_constituents=(t == "index"),
        holdings=(t in ("etf", "portfolio")),
        market_chart=(t != "portfolio"),
    )
```

★ 完成标准：
- `select_capabilities(resolve_asset("AAPL"))` → `revenue_trend=True, sector_weights=False`
- `select_capabilities(resolve_asset("^GSPC"))` → `sector_weights=True, revenue_trend=False`
- `select_capabilities(resolve_asset("SPY"))` → `holdings=True, sector_weights=True`

---

### P0-7: 新增 `backend/dashboard/cache.py`

```python
"""Dashboard 数据缓存 - TTL 内存缓存"""
import time
from typing import Any, Optional


class DashboardCache:
    """
    简易 TTL 缓存，避免每次 Dashboard 请求都重新拉取数据。

    缓存键格式: dashboard:{symbol}:{data_type}
    """

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    # TTL 配置（秒）
    TTL_SNAPSHOT = 60
    TTL_CHARTS = 300
    TTL_NEWS = 30

    def _key(self, symbol: str, data_type: str) -> str:
        return f"dashboard:{symbol.upper()}:{data_type}"

    def get(self, symbol: str, data_type: str) -> Optional[Any]:
        key = self._key(symbol, data_type)
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, symbol: str, data_type: str, value: Any, ttl: Optional[int] = None) -> None:
        if ttl is None:
            ttl = self.TTL_CHARTS
        key = self._key(symbol, data_type)
        self._store[key] = (time.time() + ttl, value)

    def invalidate(self, symbol: str) -> None:
        prefix = f"dashboard:{symbol.upper()}:"
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()


# 单例
dashboard_cache = DashboardCache()
```

★ 完成标准：`dashboard_cache.set("AAPL", "snapshot", {...}); dashboard_cache.get("AAPL", "snapshot")` 返回缓存数据；超过 TTL 后返回 `None`。

---

## Phase 1: 后端接口

> 🎯 目标：`GET /api/dashboard?symbol=AAPL` 返回结构化 JSON（真实数据源：yfinance），不再使用 mock 数据。

### P1-1: 新增 `backend/api/dashboard_router.py`

```python
"""Dashboard API 路由"""
import logging
from fastapi import APIRouter, Query
from backend.dashboard.schemas import (
    DashboardState, DashboardResponse, DashboardData,
    ActiveAsset, Capabilities, WatchItem, LayoutPrefs,
    NewsModeConfig,
)
from backend.dashboard.asset_resolver import resolve_asset
from backend.dashboard.widget_selector import select_capabilities
from backend.dashboard.cache import dashboard_cache
from backend.dashboard.errors import symbol_not_found

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


# ── 默认 Watchlist ──────────────────────────────────────
DEFAULT_WATCHLIST = [
    WatchItem(symbol="AAPL", type="equity", name="Apple Inc."),
    WatchItem(symbol="TSLA", type="equity", name="Tesla Inc."),
    WatchItem(symbol="^GSPC", type="index", name="S&P 500"),
    WatchItem(symbol="SPY", type="etf", name="SPDR S&P 500"),
    WatchItem(symbol="BTC-USD", type="crypto", name="Bitcoin"),
]


# ── 真实数据源（yfinance） ─────────────────────────────────
# 注意：Dashboard 不再提供 mock 数据；数据不足时允许字段缺失/为空列表。
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone


def _fetch_snapshot(symbol: str, asset_type: str) -> dict:
    """返回 schemas.py 定义的 SnapshotData 字段（可缺省）。"""
    t = yf.Ticker(symbol)
    # equity: revenue/eps/gross_margin/fcf from t.info
    # index/crypto: index_level from last close
    # etf: nav from navPrice or last close
    ...


def _fetch_market_chart(symbol: str) -> list[dict]:
    """返回 market_chart OHLC（time/open/high/low/close），默认 1y 日线。"""
    hist = yf.download(symbol, period="1y", interval="1d", progress=False)
    ...


def _fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    """返回 NewsItem 列表：title/url/source/ts/summary。"""
    items = yf.Ticker(symbol).news or []
    ...


# ── 路由处理 ────────────────────────────────────────────
@dashboard_router.get("", response_model=DashboardResponse)
async def get_dashboard(
    symbol: str = Query(..., min_length=1, description="资产代码"),
    type: str = Query(None, description="资产类型覆盖（可选）"),
):
    """
    Dashboard 聚合接口。

    根据 symbol 解析资产类型 → 选择能力集 → 返回聚合数据。
    """
    # 1. 解析资产
    active_asset = resolve_asset(symbol)
    logger.info(f"[Dashboard] Resolved {symbol} -> {active_asset.type}")

    # 2. 选择能力集
    capabilities = select_capabilities(active_asset)

    # 3. 构造状态
    state = DashboardState(
        active_asset=active_asset,
        capabilities=capabilities,
        watchlist=DEFAULT_WATCHLIST,
        layout_prefs=LayoutPrefs(),
        news_mode=NewsModeConfig(mode="market"),
        debug={"mock": False, "resolver_type": active_asset.type, "data_source": "yfinance"},
    )

    # 4. 聚合数据（真实数据源：yfinance；建议按 snapshot/charts/news 分别缓存）
    snapshot = dashboard_cache.get(symbol, "snapshot") or _fetch_snapshot(active_asset.symbol, active_asset.type)
    charts = dashboard_cache.get(symbol, "charts") or {"market_chart": _fetch_market_chart(active_asset.symbol)}
    news = dashboard_cache.get(symbol, "news") or {
        "market": _fetch_news("SPY"),
        "impact": _fetch_news(active_asset.symbol),
    }
    raw_data = {"snapshot": snapshot, "charts": charts, "news": news}

    # 5. 过滤：只返回 capabilities 允许的 chart 键
    filtered_charts = {}
    cap_chart_map = {
        "revenue_trend": capabilities.revenue_trend,
        "segment_mix": capabilities.segment_mix,
        "sector_weights": capabilities.sector_weights,
        "top_constituents": capabilities.top_constituents,
        "holdings": capabilities.holdings,
        "market_chart": capabilities.market_chart,
    }
    for chart_key, enabled in cap_chart_map.items():
        if enabled and chart_key in raw_data.get("charts", {}):
            filtered_charts[chart_key] = raw_data["charts"][chart_key]

    data = DashboardData(
        snapshot=raw_data.get("snapshot", {}),
        charts=filtered_charts,
        news=raw_data.get("news", {}),
    )

    return DashboardResponse(success=True, state=state, data=data)
```

★ 完成标准：
- `GET /api/dashboard?symbol=AAPL` → `state.capabilities.revenue_trend == true`，`data.charts` 含 `revenue_trend`
- `GET /api/dashboard?symbol=^GSPC` → `state.capabilities.sector_weights == true`，`data.charts` 不含 `revenue_trend`
- `GET /api/dashboard?symbol=SPY` → `state.capabilities.holdings == true`

---

### P1-2: 修改 `backend/api/main.py` — 注册路由

在 `backend/api/main.py` 的 import 区域添加：

```python
from backend.api.dashboard_router import dashboard_router
```

在 `app` 创建后添加：

```python
app.include_router(dashboard_router)
```

★ 完成标准：`uvicorn backend.api.main:app --reload` 启动后，访问 `/api/dashboard?symbol=AAPL` 返回 200。

---

## Phase 2: 前端改造

> 🎯 目标：Dashboard 页面骨架 + 状态管理 + 组件渲染。

### P2-1: 新增 `frontend/src/types/dashboard.ts`

```typescript
/**
 * Dashboard 类型定义 - 与后端 dashboard/schemas.py 一一对应
 */

export type AssetType = 'equity' | 'index' | 'etf' | 'crypto' | 'portfolio';

export interface ActiveAsset {
  symbol: string;
  type: AssetType;
  display_name: string;
}

export interface Capabilities {
  revenue_trend: boolean;
  segment_mix: boolean;
  sector_weights: boolean;
  top_constituents: boolean;
  holdings: boolean;
  market_chart: boolean;
}

export interface WatchItem {
  symbol: string;
  type: string;
  name: string;
}

export interface LayoutPrefs {
  hidden_widgets: string[];
  order: string[];
}

export type NewsModeType = 'market' | 'impact';

export interface DashboardState {
  active_asset: ActiveAsset;
  capabilities: Capabilities;
  watchlist: WatchItem[];
  layout_prefs: LayoutPrefs;
  news_mode: { mode: NewsModeType };
  debug: Record<string, unknown>;
}

export interface SnapshotData {
  revenue?: number | null;
  eps?: number | null;
  gross_margin?: number | null;
  fcf?: number | null;
  index_level?: number | null;
  nav?: number | null;
}

export interface ChartPoint {
  time?: number;
  period?: string;
  name?: string;
  value: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  weight?: number;
  symbol?: string;
}

export interface NewsItem {
  title: string;
  url: string;
  source?: string;
  ts: string;
  summary?: string;
}

export interface DashboardData {
  snapshot: SnapshotData;
  charts: Record<string, ChartPoint[]>;
  news: Record<string, NewsItem[]>;
}

export interface DashboardResponse {
  success: boolean;
  state: DashboardState;
  data: DashboardData;
}

// ── localStorage 键 ──────────────────────────────
export const STORAGE_KEYS = {
  ACTIVE_ASSET: 'fs_dashboard_active_v1',
  WATCHLIST: 'fs_dashboard_watchlist_v1',
  LAYOUT: 'fs_dashboard_layout_v1',
  NEWS_MODE: 'fs_dashboard_news_mode_v1',
} as const;

// ── Selection Context (v0.7.0 新增) ────────────────
export interface SelectionItem {
  type: 'news' | 'report';
  id: string;           // hash(title + source + ts)
  title: string;
  url?: string;
  source?: string;
  ts?: string;
  snippet?: string;     // 摘要/前100字
}
```

★ 完成标准：TypeScript 编译无错误。

---

### P2-2: 新增 `frontend/src/store/dashboardStore.ts`

```typescript
/**
 * Dashboard Zustand Store
 */
import { create } from 'zustand';
import type {
  ActiveAsset, Capabilities, WatchItem,
  LayoutPrefs, NewsModeType, DashboardData,
  SnapshotData,
} from '../types/dashboard';
import { STORAGE_KEYS } from '../types/dashboard';

interface DashboardStore {
  // ── 状态 ─────────────────────────────
  activeAsset: ActiveAsset | null;
  capabilities: Capabilities | null;
  watchlist: WatchItem[];
  layoutPrefs: LayoutPrefs;
  newsMode: NewsModeType;
  dashboardData: DashboardData | null;
  isLoading: boolean;
  error: string | null;

  // ── Selection Context (v0.7.0 新增) ──
  activeSelection: SelectionItem | null;  // 用户选中的新闻/报告

  // ── Actions ──────────────────────────
  setActiveAsset: (asset: ActiveAsset) => void;
  setCapabilities: (caps: Capabilities) => void;
  setWatchlist: (list: WatchItem[]) => void;
  addWatchItem: (item: WatchItem) => void;
  removeWatchItem: (symbol: string) => void;
  setLayoutPrefs: (prefs: LayoutPrefs) => void;
  toggleWidgetVisibility: (widgetId: string) => void;
  resetLayoutPrefs: () => void;
  setNewsMode: (mode: NewsModeType) => void;
  setDashboardData: (data: DashboardData) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  // ── Selection Context Actions (v0.7.0 新增) ──
  setActiveSelection: (selection: SelectionItem | null) => void;
  clearSelection: () => void;
}

// ── 持久化辅助函数 ──────────────────────────
const loadFromStorage = <T>(key: string, fallback: T): T => {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
};

const saveToStorage = (key: string, value: unknown): void => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(key, JSON.stringify(value));
};

// ── Store ────────────────────────────────
export const useDashboardStore = create<DashboardStore>((set) => ({
  activeAsset: loadFromStorage(STORAGE_KEYS.ACTIVE_ASSET, null),
  capabilities: null,
  watchlist: loadFromStorage(STORAGE_KEYS.WATCHLIST, []),
  layoutPrefs: loadFromStorage(STORAGE_KEYS.LAYOUT, { hidden_widgets: [], order: [] }),
  newsMode: loadFromStorage(STORAGE_KEYS.NEWS_MODE, 'market' as NewsModeType),
  dashboardData: null,
  isLoading: false,
  error: null,

  setActiveAsset: (asset) => {
    saveToStorage(STORAGE_KEYS.ACTIVE_ASSET, asset);
    set({ activeAsset: asset, error: null });
  },

  setCapabilities: (caps) => set({ capabilities: caps }),

  setWatchlist: (list) => {
    saveToStorage(STORAGE_KEYS.WATCHLIST, list);
    set({ watchlist: list });
  },

  addWatchItem: (item) =>
    set((state) => {
      const exists = state.watchlist.some(
        (w) => w.symbol.toUpperCase() === item.symbol.toUpperCase()
      );
      if (exists) return {};
      const next = [...state.watchlist, item];
      saveToStorage(STORAGE_KEYS.WATCHLIST, next);
      return { watchlist: next };
    }),

  removeWatchItem: (symbol) =>
    set((state) => {
      const next = state.watchlist.filter(
        (w) => w.symbol.toUpperCase() !== symbol.toUpperCase()
      );
      saveToStorage(STORAGE_KEYS.WATCHLIST, next);
      return { watchlist: next };
    }),

  setLayoutPrefs: (prefs) => {
    saveToStorage(STORAGE_KEYS.LAYOUT, prefs);
    set({ layoutPrefs: prefs });
  },

  toggleWidgetVisibility: (widgetId) =>
    set((state) => {
      const hidden = state.layoutPrefs.hidden_widgets;
      const next = hidden.includes(widgetId)
        ? { ...state.layoutPrefs, hidden_widgets: hidden.filter((id) => id !== widgetId) }
        : { ...state.layoutPrefs, hidden_widgets: [...hidden, widgetId] };
      saveToStorage(STORAGE_KEYS.LAYOUT, next);
      return { layoutPrefs: next };
    }),

  resetLayoutPrefs: () => {
    const defaults = { hidden_widgets: [], order: [] };
    saveToStorage(STORAGE_KEYS.LAYOUT, defaults);
    set({ layoutPrefs: defaults });
  },

  setNewsMode: (mode) => {
    saveToStorage(STORAGE_KEYS.NEWS_MODE, mode);
    set({ newsMode: mode });
  },

  setDashboardData: (data) => set({ dashboardData: data }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));
```

★ 完成标准：任意组件调用 `useDashboardStore()` 读写状态无报错；刷新页面 `layoutPrefs` 持久化。

---

### P2-3: 新增 `frontend/src/hooks/useDashboardData.ts`

```typescript
/**
 * Dashboard 数据加载 Hook
 * 封装 API 调用、abort 控制、loading/error 状态
 */
import { useEffect, useRef, useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardResponse } from '../types/dashboard';

const API_BASE = 'http://127.0.0.1:8000';

export function useDashboardData(symbol: string | null) {
  const {
    setActiveAsset, setCapabilities, setWatchlist,
    setDashboardData, setLoading, setError,
  } = useDashboardStore();

  const abortRef = useRef<AbortController | null>(null);

  const fetchDashboard = useCallback(async (sym: string) => {
    // Abort 上一次请求
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_BASE}/api/dashboard?symbol=${encodeURIComponent(sym)}`,
        { signal: controller.signal }
      );

      if (!response.ok) {
        const err = await response.json().catch(() => ({ message: 'Unknown error' }));
        throw new Error(err?.detail?.message || err?.message || `HTTP ${response.status}`);
      }

      const json: DashboardResponse = await response.json();

      if (!controller.signal.aborted) {
        setActiveAsset(json.state.active_asset);
        setCapabilities(json.state.capabilities);
        setWatchlist(json.state.watchlist);
        setDashboardData(json.data);
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Failed to load dashboard');
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [setActiveAsset, setCapabilities, setWatchlist, setDashboardData, setLoading, setError]);

  useEffect(() => {
    if (symbol) {
      fetchDashboard(symbol);
    }
    return () => {
      abortRef.current?.abort();
    };
  }, [symbol, fetchDashboard]);

  return { refetch: fetchDashboard };
}
```

★ 完成标准：`useDashboardData("AAPL")` 自动请求 API 并填充 store；快速切换 symbol 时前一个请求被 abort。

---

### P2-4: 新增 Dashboard 页面 `frontend/src/pages/Dashboard.tsx`

**布局说明：**
- 左侧：Watchlist（200px 固定宽度）
- 中间：DashboardWidgets（弹性填充）
- 右侧：ChatPanel（380px 固定宽度，复用现有对话 UI）

★ 完成标准：访问 `/dashboard?symbol=AAPL` 时三栏布局正确渲染。

---

### P2-5: 新增 `frontend/src/components/dashboard/Watchlist.tsx`

**功能要求：**
- 渲染 store 中的 watchlist
- 点击条目 → `setActiveAsset(item)` + 更新 URL `?symbol=xxx`
- 行尾外链按钮 🔗 → `https://finance.yahoo.com/quote/${symbol}`
- 底部 `[+ Add]` 按钮 → prompt 输入 symbol → `addWatchItem()`
- 右键菜单删除 → `removeWatchItem(symbol)`
- 当前激活项高亮

★ 完成标准：
- 点击 TSLA → 左侧组件切换到 TSLA，URL 更新
- 刷新不丢焦点
- 能添加/删除 watchlist

---

### P2-6: 新增 `frontend/src/components/dashboard/DashboardWidgets.tsx`

**渲染规则（按以下顺序）：**

| 组件 | 条件 | widgetId |
|------|------|----------|
| `SnapshotCard` | 总是显示 | `snapshot` |
| `RevenueTrendCard` | `caps.revenue_trend && !hidden` | `revenue_trend` |
| `SegmentMixCard` | `caps.segment_mix && !hidden` | `segment_mix` |
| `SectorWeightsCard` | `caps.sector_weights && !hidden` | `sector_weights` |
| `TopConstituentsCard` | `caps.top_constituents && !hidden` | `top_constituents` |
| `HoldingsCard` | `caps.holdings && !hidden` | `holdings` |
| `MarketChartCard` | `caps.market_chart && !hidden` | `market_chart` |
| `NewsFeed` | 总是显示 | `news_feed` |
| `MacroCard` | 占位 | `macro` |

★ 完成标准：AAPL 显示 revenue_trend + segment_mix；^GSPC 显示 sector_weights + top_constituents。

---

### P2-7: 新增卡片组件 `frontend/src/components/cards/`

每个卡片组件遵循统一接口：

```typescript
interface CardProps {
  data: ChartPoint[];  // 或各自特定的类型
  title?: string;
  loading?: boolean;
}
```

| 文件 | 图表类型 | 数据源键 |
|------|----------|----------|
| `SnapshotCard.tsx` | 4 个 KPI 指标卡 | `data.snapshot` |
| `RevenueTrendCard.tsx` | 柱状图（ECharts） | `data.charts.revenue_trend` |
| `SegmentMixCard.tsx` | 饼图 | `data.charts.segment_mix` |
| `SectorWeightsCard.tsx` | 饼图 | `data.charts.sector_weights` |
| `TopConstituentsCard.tsx` | 水平条形图/表格 | `data.charts.top_constituents` |
| `HoldingsCard.tsx` | 饼图 | `data.charts.holdings` |
| `MarketChartCard.tsx` | K线/折线（ECharts） | `data.charts.market_chart` |
| `MacroCard.tsx` | 占位文本 | 暂无 |

★ 完成标准：各卡片组件不报错，能正确消费接口返回的数据（真实数据或空态）。

---

### P2-8: 新增 `frontend/src/components/dashboard/NewsFeed.tsx`

**功能要求：**
- 顶部双按钮切换：`Market 7x24` / `Impact on {symbol}`
- 点击条目弹出详情侧抽屉
- 外链跳转到原文
- **"问这条"按钮 (v0.7.0 新增)**: 点击后设置 `activeSelection`，MiniChat/ChatInput 显示 Selection Pill

★ 完成标准：切换按钮加载不同新闻；impact 模式只显示与当前 symbol 相关新闻；点击"问这条"后 Selection Pill 显示正确引用。

---

### P2-9: 新增 `frontend/src/components/dashboard/LayoutSettingsModal.tsx`

**功能要求：**
- 列出所有 widget 名称 + Checkbox
- 勾选状态来自 `layoutPrefs.hidden_widgets`
- 确认后更新 store → 持久化 localStorage
- 提供"重置默认"按钮

★ 完成标准：隐藏某模块后刷新页面仍保持。

---

### P2-10: 修改 `frontend/src/App.tsx` — 添加视图切换

在 App.tsx 中增加 Dashboard/Chat 视图切换逻辑：

```typescript
// 读取 URL 参数判断视图
const urlParams = new URLSearchParams(window.location.search);
const dashboardSymbol = urlParams.get('symbol');
const [view, setView] = useState<'chat' | 'dashboard'>(
  dashboardSymbol ? 'dashboard' : 'chat'
);
```

★ 完成标准：`?symbol=AAPL` 渲染 Dashboard 页面；无参数渲染原有聊天页面。

---

### P2-11: 修改 `frontend/src/components/Sidebar.tsx` — 添加入口

添加 Dashboard 导航按钮。

★ 完成标准：侧栏显示 Dashboard 图标，点击切换到 Dashboard 视图。

---

### P2-12: 响应式布局设计

```
// 断点定义
// < 768px   (mobile):  单列，Watchlist 收入抽屉
// 768-1024  (tablet):  Watchlist 200px + Widgets 自适应（Chat 隐藏）
// > 1024    (desktop): Watchlist 200px + Widgets 自适应 + Chat 380px
```

修改 `frontend/src/index.css` 添加 Dashboard 布局类：

```css
.dashboard-layout {
  @apply flex h-full overflow-hidden;
}

.dashboard-watchlist {
  @apply w-[200px] shrink-0 border-r border-fin-border overflow-y-auto;
}

.dashboard-widgets {
  @apply flex-1 overflow-y-auto p-4;
}

.dashboard-chat {
  @apply w-[380px] shrink-0 border-l border-fin-border;
}

@media (max-width: 1024px) {
  .dashboard-chat { @apply hidden; }
}

@media (max-width: 768px) {
  .dashboard-watchlist { @apply hidden; }
  .dashboard-widgets { @apply p-2; }
}
```

★ 完成标准：缩小浏览器窗口时 Chat 先隐藏，再缩小时 Watchlist 隐藏。

---

## Phase 3: 新闻聚合升级

> 🎯 目标：对接真实新闻来源（默认 yfinance），并支持影响筛选（Impact）。

### P3-1: 新增 `backend/news/__init__.py`

### P3-2: 新增 `backend/news/news_service.py`

```python
"""新闻聚合服务"""

async def fetch_market_news() -> list[dict]:
    """
    抓取市场新闻（循环 RSS 源）。
    来源: Reuters RSS, Bloomberg RSS（复用现有 backend/tools/news.py 逻辑）
    返回: [{"title", "url", "source", "ts", "summary"}, ...]
    """
    ...

async def fetch_company_news(symbol: str) -> list[dict]:
    """
    抓取与 symbol 相关的新闻。
    策略: 1) 标题/摘要含 symbol  2) 调用 Finnhub company news API
    """
    ...

def dedupe(items: list[dict]) -> list[dict]:
    """根据 URL 或 title 去重"""
    ...
```

★ 完成标准：`fetch_market_news()` 返回 ≥5 条新闻；`fetch_company_news("AAPL")` 返回含 "Apple" 的新闻。

### P3-3: 新增 `GET /api/news` 端点

在 `backend/api/dashboard_router.py` 中添加：

```python
@dashboard_router.get("/news")
async def get_news(
    mode: str = Query("market", description="market | impact"),
    symbol: str = Query(None, description="symbol for impact mode"),
):
    ...
```

### P3-4: 前端订阅新闻接口

在 `NewsFeed.tsx` 中切换按钮时调用 REST API。

★ 验收：有新闻更新时页面可实时更新。

---

## Phase 4: 可选增强

> 🎯 目标：K 线时间范围切换 + 调试工具。

### P4-1: MarketChartCard 加入 timeframe 切换

- 卡片顶部下拉：`1D` / `1W` / `1M` / `6M` / `1Y`
- 切换时请求 `GET /api/dashboard/chart?symbol=AAPL&range=1M`
- 后端新增端点或复用现有 `/api/stock/kline/{ticker}`

★ 完成标准：切换 timeframe 时图表数据更新，URL 不跳变。

### P4-2: Trace/Evidence 调试显示

- 在 ChatPanel 顶部增加 Tab：`Chat` | `Evidence` | `Trace`
- Evidence Tab → 列出 EvidenceItem（从 SSE 或 ChatResponse 获取）
- Trace Tab → 列出 TraceEvent（component, event, latency）
- 提供 `debug.trace_enabled` 开关（Settings 菜单），默认 off

★ 完成标准：开发者开启后可查看 trace；用户默认不显示。

---

## Phase 5: 收尾与质量保证

### P5-1: 错误和空状态处理

| 场景 | 行为 |
|------|------|
| `/api/dashboard` 返回 4xx/5xx | 显示友好错误 + 重试按钮 |
| 某图表无数据 | 显示"暂无数据"占位 |
| News 无条目 | 显示"暂时没有相关新闻" |
| 网络断开 | Toast 提示 + 自动重试（3次指数退避） |

★ 完成标准：断网或后端报错时页面不空白，可恢复。

### P5-2: 性能优化

| 指标 | 目标 |
|------|------|
| Dashboard 首次加载 | < 2s（首次真实拉取；缓存命中更快） |
| 切换 symbol | < 500ms |
| 图表渲染 | < 200ms |

要求：
- 每个 API 请求加 loading indicator
- 切换 watchlist 时 abort 上次请求
- 使用 `useMemo` 缓存计算结果

### P5-3: 后端测试

新增 `backend/tests/test_dashboard.py`：

```python
def test_resolve_asset_equity():
    asset = resolve_asset("AAPL")
    assert asset.type == "equity"
    assert asset.display_name != ""

def test_resolve_asset_index():
    asset = resolve_asset("^GSPC")
    assert asset.type == "index"
    assert asset.display_name == "S&P 500"

def test_resolve_asset_etf():
    asset = resolve_asset("SPY")
    assert asset.type == "etf"

def test_resolve_asset_crypto():
    asset = resolve_asset("BTC-USD")
    assert asset.type == "crypto"

def test_select_capabilities_equity():
    asset = resolve_asset("AAPL")
    caps = select_capabilities(asset)
    assert caps.revenue_trend is True
    assert caps.segment_mix is True
    assert caps.sector_weights is False
    assert caps.top_constituents is False

def test_select_capabilities_index():
    asset = resolve_asset("^GSPC")
    caps = select_capabilities(asset)
    assert caps.revenue_trend is False
    assert caps.sector_weights is True
    assert caps.top_constituents is True

def test_dashboard_api_structure(client):
    response = client.get("/api/dashboard?symbol=AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "state" in data
    assert "data" in data
    assert data["state"]["active_asset"]["symbol"] == "AAPL"
    assert "snapshot" in data["data"]
    assert "charts" in data["data"]
    assert "news" in data["data"]

def test_dashboard_api_filtered_charts(client):
    """index 类型不应返回 revenue_trend"""
    response = client.get("/api/dashboard?symbol=^GSPC")
    data = response.json()
    assert "revenue_trend" not in data["data"]["charts"]
    assert "sector_weights" in data["data"]["charts"]

def test_dashboard_cache():
    from backend.dashboard.cache import dashboard_cache
    dashboard_cache.set("TEST", "snapshot", {"price": 100}, ttl=1)
    assert dashboard_cache.get("TEST", "snapshot") == {"price": 100}
    import time; time.sleep(1.1)
    assert dashboard_cache.get("TEST", "snapshot") is None
```

★ 完成标准：`pytest backend/tests/test_dashboard.py -v` 全部通过。

### P5-4: 文档更新

| 文件 | 更新内容 |
|------|----------|
| `docs/01_ARCHITECTURE.md` | 添加 Dashboard 架构图、组件树 |
| `README.md` | 添加 Dashboard 入口 `/dashboard` 介绍 + 截图 |
| `docs/DASHBOARD_DEVELOPMENT_GUIDE.md` | 补充 Dashboard 组件 API 说明 |

---

## 附录 A: 架构设计问答

### Q1: 实时对话是否考虑仪表盘数据入库 (RAG)?

**答案：是的，采用分层 RAG 策略**

| 数据层级 | 存储方式 | TTL | RAG 用途 | 实现方式 |
|---------|---------|-----|----------|----------|
| **短期缓存** | Redis/内存缓存 | 5-60s | 当前价格、涨跌幅 - 不需要RAG | 直接查询工具API |
| **中期存储** | SQLite/PostgreSQL | 1-7天 | K线历史、新闻摘要 - 支持历史分析 | 向量化后支持"上周苹果为什么跌？" |
| **长期知识库** | 向量数据库 (Chroma/Milvus) | 永久 | 财报、研报、基本面 | 支持"苹果的盈利能力如何？" |

**实施路径：**
1. 对话时，每次获取的新闻/财报数据可以**异步写入向量库**
2. 当用户问"为什么跌了？"时，先检索向量库中的相关新闻片段，然后再让 LLM 总结
3. 这样可以让 AI 回答更有"记忆"，而不是每次重新调 API 拿最新数据

### Q2: 如何决定不同股票展示什么内容？

**答案：规则引擎 + 资产类型映射 (写死的，但已参数化)**

**决策流程：**
```python
# 1. 资产类型识别
symbol = "SPY"
asset_type = resolve_asset(symbol)  # → "etf"

# 2. 能力集选择  
capabilities = select_capabilities(asset_type)  # → {sector_weights: True, holdings: True}

# 3. 前端组件渲染
if capabilities.holdings:
    render(<HoldingsCard />)
if capabilities.sector_weights:
    render(<SectorWeightsCard />)
```

**资产类型映射表：**

| 资产类型 | 启用的图表 | 示例标的 | 原因 |
|---------|----------|----------|------|
| **equity** (股票) | 营收趋势、分部收入、K线图、新闻 | AAPL, TSLA | 公司有完整财务数据 |
| **index** (指数) | 行业权重、成分股排行、K线图 | ^GSPC, ^DJI | 指数包含多个成分股 |
| **etf** (基金) | 行业权重、持仓明细、K线图 | SPY, QQQ | 基金有持仓结构数据 |
| **crypto** (加密货币) | K线图、新闻 | BTC-USD | 加密货币数据结构相对简单 |

### Q3: 图表类型 (折线/饼图) 如何决定？

**答案：确定性组件映射，不使用 LLM**

| 数据类型 | 图表类型 | 前端组件 | 选择原因 |
|---------|---------|----------|----------|
| `revenue_trend` (时间序列) | 柱状图 | `RevenueTrendCard` | 时间序列适合柱状图 |
| `segment_mix` (占比) | 饼图 | `SegmentMixCard` | 占比数据适合饼图 |
| `sector_weights` (占比) | 饼图 | `SectorWeightsCard` | 行业权重可视化 |
| `market_chart` (OHLC) | K线图/折线图 | `MarketChartCard` | 金融标准图表 |
| `top_constituents` (排名) | 表格/水平条形图 | `TopConstituentsCard` | 排名数据适合表格 |

**是否用 LLM？**
- **目前不需要**：金融数据结构是确定的（价格→K线，占比→饼图），用规则映射效率更高
- **未来可以考虑**：当用户在对话中说"画个饼图展示持仓"时，让LLM解析意图并动态选择图表类型

**总结：** 采用了**类型驱动 (Type-Driven)** 的架构，通过 `AssetType → Capabilities → Widgets` 的链式映射，实现了"指数展示成分股，股票展示财报"的差异化展示。这种方式**稳定、可预测、易于维护**，比每次都调用 LLM 来决定展示什么要高效得多。

---

## 附录 B: 一天施工建议

如果要快速起步，**第一天**可完成：

```
上午（后端）:
  ✅ P0 全部 schema、枚举、解析器、选择器、缓存
  ✅ P1 dashboard_router.py + 真实数据（yfinance） + 注册路由
  ✅ 验证: curl /api/dashboard?symbol=AAPL 返回完整 JSON

下午（前端）:
  ✅ P2-1  types/dashboard.ts
  ✅ P2-2  dashboardStore.ts
  ✅ P2-3  useDashboardData.ts
  ✅ P2-4  Dashboard.tsx 页面骨架
  ✅ P2-5  Watchlist.tsx 可点击切换
  ✅ P2-6  DashboardWidgets.tsx 条件渲染
  ✅ P2-7  SnapshotCard + RevenueTrendCard（至少2个卡片）
  ✅ P2-10 App.tsx 视图切换

效果: 基础"仪表盘 + 对话 + 切换资产 + 卡片"可用
```

---

## 附录 C: 未来扩展路线

> 仅列参考，不在本计划实施范围内。

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 真实财报数据源 | yfinance（可选 Finnhub/Alpha Vantage） | 🔴 高 |
| SSE 实时推送 | 新闻 + 价格实时推送到前端 | 🔴 高 |
| ETF/Portfolio 类型完善 | 扩展 AssetResolver + HoldingsCard | 🟡 中 |
| 图表主题切换 | ECharts 深色/浅色 | 🟡 中 |
| 用户登录系统 | 偏好同步到数据库而非 localStorage | 🟡 中 |
| 移动端适配 | 抽屉式 Watchlist + 底部 Tab | 🟢 低 |
| 多语言 i18n | 中/英切换 | 🟢 低 |
| 组件拖拽排序 | react-beautiful-dnd | 🟢 低 |

---

## 附录 C: localStorage 键命名规范

| 键 | 描述 | 格式 | 版本 |
|---|---|---|---|
| `fs_dashboard_active_v1` | 上次选中资产 | `ActiveAsset` | v1 |
| `fs_dashboard_watchlist_v1` | 自选列表 | `WatchItem[]` | v1 |
| `fs_dashboard_layout_v1` | 布局偏好 | `LayoutPrefs` | v1 |
| `fs_dashboard_news_mode_v1` | 新闻模式 | `"market" \| "impact"` | v1 |

**版本迁移规则：** 当 schema 变更时，实现 `migrateStorageV1ToV2()` 函数，读取旧版数据并转换。

---

*本文档为 FinSight Dashboard 实施蓝图，按 Phase 依次执行即可从零落地至可用仪表盘。*
