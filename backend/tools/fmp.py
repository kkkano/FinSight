"""
Financial Modeling Prep (FMP) API 工具模块

提供以下数据：
- 产品线收入分部 (segment_mix)
- 地区收入分部
- ETF 板块权重 (sector_weights)
- ETF 持仓 (holdings)
- 指数成分股 (constituents)

API 文档: https://financialmodelingprep.com/developer/docs/

免费版限制: 250 次/天，建议配合长 TTL 缓存使用
"""
import logging
from typing import Any, Optional

import requests

from backend.tools.env import FMP_API_KEY

logger = logging.getLogger(__name__)

# FMP API 基础 URL
FMP_BASE_URL = "https://financialmodelingprep.com/api"

# 请求超时（秒）
REQUEST_TIMEOUT = 5


def _fmp_request(endpoint: str, params: Optional[dict] = None) -> Optional[Any]:
    """
    发送 FMP API 请求

    Args:
        endpoint: API 端点（如 "/v4/revenue-product-segmentation"）
        params: 额外的查询参数

    Returns:
        JSON 响应数据，失败返回 None
    """
    if not FMP_API_KEY:
        logger.debug("[FMP] API key not configured, skipping request")
        return None

    url = f"{FMP_BASE_URL}{endpoint}"
    query_params = {"apikey": FMP_API_KEY}
    if params:
        query_params.update(params)

    try:
        response = requests.get(url, params=query_params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        data = response.json()

        # FMP 错误响应格式：{"Error Message": "..."}
        if isinstance(data, dict) and "Error Message" in data:
            logger.info(f"[FMP] API error: {data['Error Message']}")
            return None

        return data

    except requests.exceptions.Timeout:
        logger.info(f"[FMP] Request timeout for {endpoint}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.info(f"[FMP] HTTP error for {endpoint}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.info(f"[FMP] Request error for {endpoint}: {e}")
        return None
    except ValueError as e:
        logger.info(f"[FMP] JSON parse error for {endpoint}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 收入分部数据
# ══════════════════════════════════════════════════════════════════════════════


def get_revenue_product_segmentation(symbol: str) -> list[dict]:
    """
    获取产品线收入分部

    例如 AAPL 的 iPhone, Mac, iPad, Services, Wearables

    API: /v4/revenue-product-segmentation

    Args:
        symbol: 股票代码（如 "AAPL"）

    Returns:
        list[dict]: 分部数据
            [{
                "segment": "iPhone",
                "revenue": 200000000000,
                "percentage": 52.5
            }, ...]
    """
    data = _fmp_request(
        "/v4/revenue-product-segmentation",
        params={"symbol": symbol, "structure": "flat", "period": "annual"},
    )

    if not data or not isinstance(data, list):
        return []

    # FMP 返回多个年份的数据，取最新的一年
    if len(data) == 0:
        return []

    # 获取最新年份的数据
    latest = data[0] if data else {}
    segments_raw = latest.get(symbol, {}) if isinstance(latest, dict) else {}

    if not segments_raw:
        # 尝试其他格式
        for item in data:
            if isinstance(item, dict):
                for key, value in item.items():
                    if key != "date" and isinstance(value, dict):
                        segments_raw = value
                        break
            if segments_raw:
                break

    if not segments_raw or not isinstance(segments_raw, dict):
        return []

    # 转换为标准格式
    segments = []
    total_revenue = sum(v for v in segments_raw.values() if isinstance(v, (int, float)))

    for seg_name, revenue in segments_raw.items():
        if not isinstance(revenue, (int, float)) or revenue <= 0:
            continue
        percentage = (revenue / total_revenue * 100) if total_revenue > 0 else 0
        segments.append({
            "segment": seg_name,
            "revenue": revenue,
            "percentage": round(percentage, 2),
        })

    # 按收入排序
    segments.sort(key=lambda x: x["revenue"], reverse=True)

    logger.info(f"[FMP] revenue_product_segmentation OK for {symbol}: {len(segments)} segments")
    return segments


def get_revenue_geographic_segmentation(symbol: str) -> list[dict]:
    """
    获取地区收入分部

    例如 AAPL 的 Americas, Europe, Greater China, Japan, Rest of Asia Pacific

    API: /v4/revenue-geographic-segmentation

    Args:
        symbol: 股票代码

    Returns:
        list[dict]: 地区分部数据
            [{
                "region": "Americas",
                "revenue": 150000000000,
                "percentage": 40.2
            }, ...]
    """
    data = _fmp_request(
        "/v4/revenue-geographic-segmentation",
        params={"symbol": symbol, "structure": "flat", "period": "annual"},
    )

    if not data or not isinstance(data, list):
        return []

    if len(data) == 0:
        return []

    # 获取最新年份的数据
    latest = data[0] if data else {}
    regions_raw = latest.get(symbol, {}) if isinstance(latest, dict) else {}

    if not regions_raw:
        for item in data:
            if isinstance(item, dict):
                for key, value in item.items():
                    if key != "date" and isinstance(value, dict):
                        regions_raw = value
                        break
            if regions_raw:
                break

    if not regions_raw or not isinstance(regions_raw, dict):
        return []

    # 转换为标准格式
    regions = []
    total_revenue = sum(v for v in regions_raw.values() if isinstance(v, (int, float)))

    for region_name, revenue in regions_raw.items():
        if not isinstance(revenue, (int, float)) or revenue <= 0:
            continue
        percentage = (revenue / total_revenue * 100) if total_revenue > 0 else 0
        regions.append({
            "region": region_name,
            "revenue": revenue,
            "percentage": round(percentage, 2),
        })

    regions.sort(key=lambda x: x["revenue"], reverse=True)

    logger.info(f"[FMP] revenue_geographic_segmentation OK for {symbol}: {len(regions)} regions")
    return regions


# ══════════════════════════════════════════════════════════════════════════════
# ETF 数据
# ══════════════════════════════════════════════════════════════════════════════


def get_etf_sector_weights(symbol: str) -> list[dict]:
    """
    获取 ETF 板块权重

    API: /v3/etf-sector-weightings/{symbol}

    Args:
        symbol: ETF 代码（如 "SPY", "QQQ"）

    Returns:
        list[dict]: 板块权重
            [{
                "sector": "Technology",
                "weight": 28.5
            }, ...]
    """
    data = _fmp_request(f"/v3/etf-sector-weightings/{symbol}")

    if not data or not isinstance(data, list):
        return []

    sectors = []
    for item in data:
        if not isinstance(item, dict):
            continue

        sector = item.get("sector", "")
        weight_str = item.get("weightPercentage", "0%")

        # 解析权重百分比（去掉 % 符号）
        try:
            weight = float(str(weight_str).replace("%", "").strip())
        except (ValueError, TypeError):
            weight = 0

        if sector and weight > 0:
            sectors.append({
                "sector": sector,
                "weight": weight,
            })

    sectors.sort(key=lambda x: x["weight"], reverse=True)

    logger.info(f"[FMP] etf_sector_weights OK for {symbol}: {len(sectors)} sectors")
    return sectors


def get_etf_holdings(symbol: str, limit: int = 50) -> list[dict]:
    """
    获取 ETF 持仓

    API: /v3/etf-holder/{symbol}

    Args:
        symbol: ETF 代码
        limit: 返回数量限制

    Returns:
        list[dict]: 持仓列表
            [{
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "weight": 7.2,
                "shares": 123456789,
                "value": 12345678900
            }, ...]
    """
    data = _fmp_request(f"/v3/etf-holder/{symbol}")

    if not data or not isinstance(data, list):
        return []

    holdings = []
    for item in data:
        if not isinstance(item, dict):
            continue

        asset = item.get("asset", "")
        name = item.get("name", "")
        weight_str = item.get("weightPercentage", "0")
        shares = item.get("sharesNumber", 0)
        value = item.get("marketValue", 0)

        # 解析权重
        try:
            weight = float(str(weight_str).replace("%", "").strip())
        except (ValueError, TypeError):
            weight = 0

        if asset:
            holdings.append({
                "symbol": asset,
                "name": name or asset,
                "weight": weight,
                "shares": shares or 0,
                "value": value or 0,
            })

    holdings.sort(key=lambda x: x["weight"], reverse=True)

    logger.info(f"[FMP] etf_holdings OK for {symbol}: {len(holdings[:limit])} holdings")
    return holdings[:limit]


# ══════════════════════════════════════════════════════════════════════════════
# 指数数据
# ══════════════════════════════════════════════════════════════════════════════


# 指数符号到 FMP 端点的映射
INDEX_CONSTITUENTS_MAP = {
    "^GSPC": "/v3/sp500_constituent",     # S&P 500
    "^SPX": "/v3/sp500_constituent",
    "^NDX": "/v3/nasdaq_constituent",     # Nasdaq 100
    "^IXIC": "/v3/nasdaq_constituent",
    "^DJI": "/v3/dowjones_constituent",   # Dow Jones
}


def get_index_constituents(symbol: str, limit: int = 10) -> list[dict]:
    """
    获取指数成分股

    支持的指数:
    - ^GSPC / ^SPX: S&P 500
    - ^NDX / ^IXIC: Nasdaq 100
    - ^DJI: Dow Jones

    Args:
        symbol: 指数代码
        limit: 返回数量限制

    Returns:
        list[dict]: 成分股列表
            [{
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "weight": 7.2
            }, ...]
    """
    endpoint = INDEX_CONSTITUENTS_MAP.get(symbol)
    if not endpoint:
        logger.debug(f"[FMP] Unknown index symbol: {symbol}")
        return []

    data = _fmp_request(endpoint)

    if not data or not isinstance(data, list):
        return []

    constituents = []
    for item in data:
        if not isinstance(item, dict):
            continue

        sym = item.get("symbol", "")
        name = item.get("name", "")
        sector = item.get("sector", "")
        sub_sector = item.get("subSector", "")

        if sym:
            constituents.append({
                "symbol": sym,
                "name": name or sym,
                "sector": sector or sub_sector or "Unknown",
                "weight": 0,  # FMP 免费版不提供权重，需要另外计算
            })

    # 按符号排序（没有权重信息）
    constituents.sort(key=lambda x: x["symbol"])

    logger.info(f"[FMP] index_constituents OK for {symbol}: {len(constituents[:limit])} constituents")
    return constituents[:limit]


# ══════════════════════════════════════════════════════════════════════════════
# 公司概况
# ══════════════════════════════════════════════════════════════════════════════


def get_company_profile(symbol: str) -> Optional[dict]:
    """
    获取公司概况

    API: /v3/profile/{symbol}

    Args:
        symbol: 股票代码

    Returns:
        dict: 公司信息
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "industry": "Consumer Electronics",
                "sector": "Technology",
                "country": "US",
                "mktCap": 2800000000000,
                ...
            }
    """
    data = _fmp_request(f"/v3/profile/{symbol}")

    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    profile = data[0]
    if not isinstance(profile, dict):
        return None

    logger.info(f"[FMP] company_profile OK for {symbol}")
    return profile


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════


def is_fmp_configured() -> bool:
    """检查 FMP API 是否已配置"""
    return bool(FMP_API_KEY)


def get_fmp_status() -> dict:
    """获取 FMP API 状态信息"""
    return {
        "configured": is_fmp_configured(),
        "base_url": FMP_BASE_URL,
        "timeout": REQUEST_TIMEOUT,
    }
