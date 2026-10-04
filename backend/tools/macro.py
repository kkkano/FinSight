import logging
import re
from datetime import date, datetime, timezone
from calendar import monthrange
from typing import Dict, Any

import requests

from .env import FRED_API_KEY
from .http import _http_get
from .search import search
from .financial_facts import fact_number

logger = logging.getLogger(__name__)

def get_market_sentiment() -> str:
    """
    获取市场情绪指标 - CNN Fear & Greed Index
    使用更完整的请求头来模拟浏览器，提高成功率。
    """
    try:
        # 主要API地址
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        
        # 伪装成一个从CNN官网页面发出请求的真实浏览器
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            # 'Referer' 是最关键的头信息，告诉服务器请求的来源页面
            'Referer': 'https://www.cnn.com/markets/fear-and-greed',
            'Origin': 'https://www.cnn.com',
        }
        
        logger.info("Attempting to fetch from CNN API with full headers...")
        response = _http_get(url, headers=headers, timeout=10)
        
        # 如果状态码不是 2xx，则会引发 HTTPError 异常
        response.raise_for_status() 
        
        data = response.json()
        score = float(data['fear_and_greed']['score'])
        rating = data['fear_and_greed']['rating']
        
        logger.info("CNN API fetch successful!")
        return f"CNN Fear & Greed Index: {score:.1f} ({rating})"
    
    except requests.exceptions.HTTPError as http_err:
        logger.info(f"CNN API failed with HTTP error: {http_err}. Trying fallback search...")
    except Exception as e:
        # 捕获其他所有可能的异常，例如网络问题、JSON解析错误等
        logger.info(f"CNN API failed with other error: {e}. Trying fallback search...")
    # --- 如果上面的 try 代码块出现任何异常，则执行下面的回退逻辑 ---
    try:
        search_result = search("CNN Fear and Greed Index current value today")
        # 使用正则表达式从搜索结果中提取数值和评级
        match = re.search(r'(?:Index|Score)[:\s]*(\d+\.?\d*)\s*\((\w+\s?\w*)\)', search_result, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            rating = match.group(2)
            logger.info("Fallback search successful!")
            return f"CNN Fear & Greed Index (via search): {score:.1f} ({rating})"
    except Exception as search_e:
        logger.info(f"Search fallback also failed: {search_e}")
    
    # 如果所有方法都失败了，返回一个通用错误信息
    return "Fear & Greed Index: Unable to fetch. Please check manually."

def get_economic_events() -> str:
    """搜索当前月份的主要美国经济事件"""
    now = datetime.now()
    query = f"major upcoming US economic events {now.strftime('%B %Y')} (FOMC, CPI, jobs report)"
    return search(query)


def _fred_as_of_parameters(as_of: str | None) -> dict[str, str]:
    if not as_of:
        return {}
    if len(as_of) == 10:
        cutoff = date.fromisoformat(as_of)
    else:
        point = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if point.tzinfo is None:
            raise ValueError("fred_as_of_requires_timezone")
        cutoff = point.astimezone(timezone.utc).date()
    return {"realtime_start": cutoff.isoformat(), "realtime_end": cutoff.isoformat()}


def _fred_employment_indicators(indicators: list[str], api_key: str, as_of: str | None) -> dict[str, Any]:
    output: dict[str, Any] = {"indicator_metadata": {}, "metric_gaps": {}, "employment_report": {"published_at": None}}
    months = []
    for key in indicators:
        sid = "PAYEMS" if key == "nonfarm_payroll_change" else "UNRATE"
        output[key] = None
        try:
            params = {"series_id": sid, "api_key": api_key, "file_type": "json"}
            params.update(_fred_as_of_parameters(as_of))
            response = _http_get("https://api.stlouisfed.org/fred/series", params=params, timeout=10)
            series = response.json().get("seriess", []) if response.status_code == 200 else []
            metadata = next((item for item in series if item.get("id") == sid), None)
            if not metadata or metadata.get("frequency") != "Monthly" or metadata.get("units") != ("Thousands of Persons" if sid == "PAYEMS" else "Percent") or metadata.get("seasonal_adjustment") != "Seasonally Adjusted":
                raise ValueError("employment_series_definition_not_verified")
            observation_params = {**params, "sort_order": "desc", "limit": 2 if sid == "PAYEMS" else 1}
            response = _http_get("https://api.stlouisfed.org/fred/series/observations", params=observation_params, timeout=10)
            observations = response.json().get("observations", []) if response.status_code == 200 else []
            if len(observations) < (2 if sid == "PAYEMS" else 1):
                raise ValueError("employment_observations_missing")
            rows = sorted(observations, key=lambda row: row.get("date", ""), reverse=True)
            latest = rows[0]
            point = date.fromisoformat(latest["date"])
            current = fact_number(latest.get("value"))
            if current is None:
                raise ValueError("latest_employment_value_missing")
            source_url = f"https://fred.stlouisfed.org/series/{sid}"
            lineage = [{"series_id": sid, "value": current, "observation_date": latest["date"],
                "unit": "thousands_of_persons" if sid == "PAYEMS" else "percent", "source_url": source_url,
                "realtime_start": latest.get("realtime_start"), "realtime_end": latest.get("realtime_end")}]
            value = current
            if sid == "PAYEMS":
                previous = rows[1]
                prior = date.fromisoformat(previous["date"])
                prior_value = fact_number(previous.get("value"))
                if prior_value is None or (point.year * 12 + point.month) - (prior.year * 12 + prior.month) != 1:
                    raise ValueError("adjacent_payroll_month_missing")
                value = (current - prior_value) * 1000
                lineage.append({"series_id": sid, "value": prior_value, "observation_date": previous["date"],
                    "unit": "thousands_of_persons", "source_url": source_url,
                    "realtime_start": previous.get("realtime_start"), "realtime_end": previous.get("realtime_end")})
            updated = None
            if metadata.get("last_updated"):
                parsed = datetime.fromisoformat(metadata["last_updated"].replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    updated = parsed.astimezone(timezone.utc).isoformat()
            report_month = point.strftime("%Y-%m")
            output[key] = value
            output["indicator_metadata"][key] = {
                "subject": "US", "metric": key, "value": value, "series_id": sid, "source": "FRED", "source_url": source_url,
                "unit": "persons" if sid == "PAYEMS" else "percent", "frequency": "monthly", "report_month": report_month,
                "observation_date": latest["date"], "period_start": point.replace(day=1).isoformat(),
                "period_end": point.replace(day=monthrange(point.year, point.month)[1]).isoformat(),
                "definition": "monthly_nonfarm_payroll_net_change" if sid == "PAYEMS" else "household_survey_unemployment_rate",
                "seasonal_adjustment": "seasonally_adjusted", "transformation": "difference" if sid == "PAYEMS" else "lin",
                "formula": "(current_PAYEMS_thousands - previous_PAYEMS_thousands) * 1000" if sid == "PAYEMS" else None,
                "derivation_inputs": lineage, "source_updated_at": updated, "published_at": None,
                "timestamp_semantics": "source_update", "source_time_status": "provided" if updated else "unknown",
                "limitations": ["FRED 当前修订口径；报告月及序列更新时间不是 BLS 原始发布时刻。",
                    "新增非农为机构调查净变动，失业率为家庭调查，不能混成同一人数口径。"],
            }
            months.append(report_month)
        except Exception as exc:
            output["metric_gaps"][key] = str(exc) if isinstance(exc, ValueError) else "fred_employment_unavailable"
    output["employment_report"].update(report_month=months[0] if len(set(months)) == 1 and len(months) == len(indicators) else None,
        periods_match=len(set(months)) == 1 and len(months) == len(indicators),
        missing_metrics=list(output["metric_gaps"]) + ["published_at"])
    if len(set(months)) > 1:
        output["employment_report"]["missing_metrics"].append("report_month_alignment")
    return output


def get_fred_data(series_id: str = None, indicators: list[str] | None = None, as_of: str | None = None) -> Dict[str, Any]:
    """
    从 FRED (Federal Reserve Economic Data) 获取宏观经济数据

    常用 series_id:
    - CPIAUCSL: CPI (Consumer Price Index)
    - FEDFUNDS: Federal Funds Rate
    - GDP: Gross Domestic Product
    - UNRATE: Unemployment Rate
    - DGS10: 10-Year Treasury Rate
    - T10Y2Y: 10Y-2Y Treasury Spread (衰退指标)
    """
    result = {
        "cpi": None,
        "fed_rate": None,
        "gdp_growth": None,
        "unemployment": None,
        "treasury_10y": None,
        "yield_spread": None,
        "status": "success",
        "source": "FRED",
        "as_of": datetime.now().isoformat(),
        "indicator_metadata": {},
    }

    # FRED API 配置
    api_key = FRED_API_KEY
    base_url = "https://api.stlouisfed.org/fred/series/observations"

    # 要获取的指标
    series_map = {
        "cpi": "CPIAUCSL",
        "fed_rate": "FEDFUNDS",
        "gdp_growth": "A191RL1Q225SBEA",  # Real GDP Growth Rate
        "unemployment": "UNRATE",
        "treasury_10y": "DGS10",
        "yield_spread": "T10Y2Y"
    }
    if indicators is not None:
        selected = list(dict.fromkeys(indicators))
        unknown = set(selected) - set(series_map) - {"nonfarm_payroll_change"}
        if unknown or series_id or not selected:
            return {**result, "status": "data_unavailable", "unavailable_reason": "invalid_indicator_selector"}
        employment = [key for key in selected if key in {"nonfarm_payroll_change", "unemployment"}]
        if employment and api_key:
            employment_payload = _fred_employment_indicators(employment, api_key, as_of)
            result.update({key: value for key, value in employment_payload.items() if key != "indicator_metadata"})
            result["indicator_metadata"].update(employment_payload["indicator_metadata"])
        elif employment:
            result.update(status="data_unavailable", unavailable_reason="FRED_API_KEY not configured")
            result["metric_gaps"] = {key: "fred_api_key_missing" for key in employment}
            result["nonfarm_payroll_change"] = None
        series_map = {key: value for key, value in series_map.items() if key in selected and key not in employment}

    # 如果指定了单个 series_id，只获取该数据
    if series_id:
        series_map = {"custom": series_id}

    for key, sid in series_map.items():
        try:
            params = {
                "series_id": sid,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1
            }
            if key == "cpi":
                params["units"] = "pc1"
            params.update(_fred_as_of_parameters(as_of))

            if api_key:
                response = _http_get(base_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    observations = data.get("observations", [])
                    if observations:
                        value = observations[0].get("value", ".")
                        if value != ".":
                            result[key] = float(value)
                            result["indicator_metadata"][key] = {
                                "series_id": sid, "source": "FRED", "period_end": observations[0].get("date"),
                                "unit": "percent" if key != "custom" else "unknown",
                                "definition": "inflation_yoy" if key == "cpi" else key,
                                "transformation": "pc1" if key == "cpi" else "lin",
                            }
            else:
                # 无 API key：诚实返回不可用，绝不编造数值（P0-1）
                result["status"] = "data_unavailable"
                result["unavailable_reason"] = "FRED_API_KEY not configured"
                break

        except Exception as e:
            logger.info("[FRED] Failed to fetch %s: %s", sid, e.__class__.__name__)
            continue

    # 格式化输出
    if result.get("cpi"):
        result["cpi_formatted"] = f"{result['cpi']:.1f}% (同比)"
    if result.get("fed_rate"):
        result["fed_rate_formatted"] = f"{result['fed_rate']:.2f}%"
    if result.get("unemployment"):
        result["unemployment_formatted"] = f"{result['unemployment']:.1f}%"
    if result.get("gdp_growth"):
        result["gdp_growth_formatted"] = f"{result['gdp_growth']:.1f}%"
    if result.get("treasury_10y"):
        result["treasury_10y_formatted"] = f"{result['treasury_10y']:.2f}%"
    if result.get("yield_spread"):
        result["yield_spread_formatted"] = f"{result['yield_spread']:.2f}%"
        # 收益率曲线倒挂警告
        if result["yield_spread"] < 0:
            result["recession_warning"] = True
    if result.get("nonfarm_payroll_change") is not None:
        result["nonfarm_payroll_change_formatted"] = f"{result['nonfarm_payroll_change']:+,.0f} 人（月度净变动）"
    if indicators is not None:
        result.update(kind="macro_context", metric="macro_data", source_url="https://fred.stlouisfed.org/",
            subject="US", requested_indicators=list(indicators))
        result["structured_data"] = dict(result)

    return result
