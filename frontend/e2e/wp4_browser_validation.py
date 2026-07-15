from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, sync_playwright


BASE_URL = "http://127.0.0.1:4273"
API_PATTERN = "http://127.0.0.1:8000/**"
RUN_ID = "22222222-2222-4222-8222-222222222222"
PREDICTION_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "33333333-3333-4333-8333-333333333333"
EVIDENCE_DIR = Path(__file__).resolve().parents[2] / ".omx" / "evidence" / "wp4"


def bars() -> list[dict[str, float | int | str]]:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows: list[dict[str, float | int | str]] = []
    for index in range(45):
        current = start + timedelta(days=index)
        base = 198.0 + index * 0.38
        close = base + (1.1 if index % 3 else -0.45)
        rows.append(
            {
                "time": int(current.timestamp()),
                "period": current.date().isoformat(),
                "open": round(base, 2),
                "high": round(max(base, close) + 1.4, 2),
                "low": round(min(base, close) - 1.2, 2),
                "close": round(close, 2),
                "volume": 42_000_000 + index * 130_000,
            }
        )
    return rows


MARKET_BARS = bars()

PREDICTION = {
    "prediction_id": PREDICTION_ID,
    "run_id": RUN_ID,
    "agent": "prediction_analyst",
    "symbol": "AAPL",
    "direction": "long",
    "anchor": {"timeframe": "1d", "time": "2026-07-10", "price": 213.2},
    "entry": 214.0,
    "entry_type": "limit",
    "stop": 207.5,
    "target1": 221.0,
    "target2": 228.0,
    "confidence": 0.76,
    "thesis": "真实日线趋势、动量和近期证据共同支持偏多判断。",
    "scenarios": [
        {"name": "base", "probability": 0.62, "invalidation": "收盘跌破 207.50"},
        {"name": "bull", "probability": 0.24, "invalidation": "量价背离"},
    ],
    "source_type": "ai",
    "prompt_version": "prediction-v1",
    "evidence_provider": "twelve_data",
    "evidence_as_of": "2026-07-15T08:00:00Z",
    "status": "open",
    "created_at": "2026-07-15T08:01:00Z",
    "updated_at": "2026-07-15T08:01:18Z",
}

RUN = {
    "id": RUN_ID,
    "symbol": "AAPL",
    "timeframe": "1d",
    "status": "succeeded",
    "prompt_version": "prediction-v1",
    "provider_attempts": 1,
    "prompt_tokens": 640,
    "completion_tokens": 220,
    "total_tokens": 860,
    "latency_ms": 18_420,
    "prediction_id": PREDICTION_ID,
    "anchor_time": "2026-07-10",
    "anchor_price": 213.2,
    "market_provider": "twelve_data",
    "market_as_of": "2026-07-15T08:00:00Z",
    "llm_provider": "openai_compatible",
    "llm_model": "gpt-5.6-luna",
    "started_at": "2026-07-15T08:01:00Z",
    "completed_at": "2026-07-15T08:01:18Z",
    "created_at": "2026-07-15T08:01:00Z",
    "updated_at": "2026-07-15T08:01:18Z",
}

OUTCOME = {
    "prediction_id": PREDICTION_ID,
    "status": "hit_target",
    "entry_time": "2026-07-15T08:01:18Z",
    "entry_price": 214.0,
    "resolved_at": "2026-07-15T20:00:00Z",
    "resolution_reason": "target1_reached",
    "evaluated_through": "2026-07-15T20:00:00Z",
    "pct_since_anchor": 3.66,
    "market_provider": "twelve_data",
    "market_as_of": "2026-07-15T20:00:00Z",
    "algorithm_version": "outcome-v1",
}


def dashboard_payload() -> dict:
    return {
        "success": True,
        "state": {
            "active_asset": {"symbol": "AAPL", "type": "equity", "display_name": "Apple Inc."},
            "capabilities": {
                "revenue_trend": True,
                "segment_mix": False,
                "sector_weights": False,
                "top_constituents": False,
                "holdings": False,
                "market_chart": True,
            },
            "watchlist": [{"symbol": "AAPL", "type": "equity", "name": "Apple"}],
            "layout_prefs": {"hidden_widgets": [], "order": []},
            "news_mode": {"mode": "market"},
            "debug": {},
        },
        "data": {
            "snapshot": {"revenue": 391_000_000_000, "eps": 6.45, "fcf": 99_000_000_000},
            "charts": {"market_chart": MARKET_BARS},
            "news": {
                "market": [
                    {
                        "title": "Apple 发布最新季度经营更新",
                        "url": "https://example.test/apple-update",
                        "source": "SEC",
                        "ts": "2026-07-15T07:00:00Z",
                    }
                ],
                "impact": [],
            },
            "meta": {
                "market_chart": {
                    "provider": "twelve_data",
                    "source_type": "commercial_api",
                    "as_of": "2026-07-15T08:00:00Z",
                    "latency_ms": 82,
                    "fallback_used": False,
                    "confidence": 0.99,
                }
            },
            "valuation": {
                "market_cap": 3_200_000_000_000,
                "trailing_pe": 31.2,
                "forward_pe": 28.4,
                "price_to_book": 42.0,
                "price_to_sales": 8.1,
                "ev_to_ebitda": 24.5,
                "dividend_yield": 0.0045,
                "beta": 1.18,
                "week52_high": 237.49,
                "week52_low": 164.08,
            },
            "financials": {
                "periods": ["2024", "2025", "2026"],
                "revenue": [383_000_000_000, 391_000_000_000, 407_000_000_000],
                "gross_profit": [169_000_000_000, 180_000_000_000, 190_000_000_000],
                "operating_income": [114_000_000_000, 121_000_000_000, 128_000_000_000],
                "net_income": [97_000_000_000, 101_000_000_000, 108_000_000_000],
                "eps": [6.16, 6.45, 6.91],
                "total_assets": [352_000_000_000, 365_000_000_000, 378_000_000_000],
                "total_liabilities": [290_000_000_000, 294_000_000_000, 298_000_000_000],
                "operating_cash_flow": [111_000_000_000, 118_000_000_000, 123_000_000_000],
                "free_cash_flow": [99_000_000_000, 104_000_000_000, 109_000_000_000],
            },
            "technicals": {
                "close": 215.24,
                "trend": "uptrend",
                "momentum": "positive",
                "ma5": 213.8,
                "ma20": 209.4,
                "ma50": 204.1,
                "rsi": 61.4,
                "rsi_state": "neutral",
                "macd": 2.14,
                "macd_signal": 1.82,
                "macd_hist": 0.32,
                "support_levels": [207.5, 202.0],
                "resistance_levels": [221.0, 228.0],
                "avg_volume": 47_000_000,
            },
            "peers": {"subject_symbol": "AAPL", "peers": []},
            "peers_fallback_reason": "本次验收未请求同行数据",
        },
    }


def report_payload() -> dict:
    return {
        "report_id": REPORT_ID,
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "title": "AAPL 证据化研究报告",
        "summary": "真实行情与公开材料支持当前核心结论。",
        "sentiment": "bullish",
        "confidence_score": 0.78,
        "generated_at": "2026-07-15T08:30:00Z",
        "sections": [],
        "citations": [],
        "risks": ["需求波动", "估值压缩"],
        "recommendation": "持续跟踪证据变化。",
        "tags": ["AAPL", "research"],
    }


def fulfill_json(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def install_api_mock(page: Page) -> dict[str, bool]:
    state = {"generated": False}

    def handler(route: Route) -> None:
        request = route.request
        path = urlparse(request.url).path

        if path == "/health":
            fulfill_json(route, {"status": "ok", "components": {"live_tools": {"status": "ok"}}})
        elif path == "/api/dashboard":
            fulfill_json(route, dashboard_payload())
        elif path.startswith("/api/stock/kline/"):
            fulfill_json(
                route,
                {
                    "ticker": "AAPL",
                    "cached": False,
                    "data": {
                        "data": MARKET_BARS,
                        "kline_data": MARKET_BARS,
                        "provider": "twelve_data",
                        "source": "twelve_data",
                        "as_of": "2026-07-15T08:00:00Z",
                        "freshness_seconds": 60,
                        "quality": "trusted",
                        "degraded": False,
                        "error_code": None,
                        "attempted_providers": ["twelve_data"],
                        "cached": False,
                    },
                },
            )
        elif path.startswith("/api/stock/price/"):
            fulfill_json(
                route,
                {
                    "ticker": path.rsplit("/", 1)[-1],
                    "data": {
                        "data": {"price": 215.24, "change": 2.11, "change_percent": 0.99},
                        "provider": "twelve_data",
                        "quality": "trusted",
                    },
                },
            )
        elif path == "/api/monitor/leases" and request.method == "POST":
            fulfill_json(
                route,
                {
                    "lease": {
                        "id": "44444444-4444-4444-8444-444444444444",
                        "session_id": "public:wp4-browser-user:default",
                        "symbol": "AAPL",
                        "lease_token": "local-lease-token",
                        "expires_at": "2026-07-15T09:00:00Z",
                    }
                },
            )
        elif path.startswith("/api/monitor/leases/"):
            fulfill_json(route, {"success": True})
        elif path == "/api/predictions/generate" and request.method == "POST":
            queued = {**RUN, "status": "queued", "prediction_id": None, "completed_at": None}
            fulfill_json(route, {"created": True, "idempotent_reuse": False, "run": queued}, status=202)
        elif path == f"/api/predictions/runs/{RUN_ID}":
            state["generated"] = True
            fulfill_json(route, {"run": RUN})
        elif path == "/api/predictions/latest":
            payload = {"prediction": PREDICTION, "outcome": None} if state["generated"] else {"prediction": None, "outcome": None}
            fulfill_json(route, payload)
        elif path == "/api/predictions/history":
            fulfill_json(route, {"items": [{"prediction": PREDICTION, "outcome": OUTCOME}], "limit": 100, "offset": 0})
        elif path == "/api/predictions/stats":
            bucket = {"predictions": 1, "resolved": 1, "hits": 1, "misses": 0, "invalidated": 0, "hit_rate": 1.0}
            fulfill_json(
                route,
                {
                    "stats": {
                        **bucket,
                        "days": 90,
                        "symbol": None,
                        "by_direction": {"long": bucket},
                        "by_source": {"ai": bucket},
                    }
                },
            )
        elif path == f"/api/predictions/{PREDICTION_ID}":
            fulfill_json(route, {"prediction": PREDICTION, "outcome": OUTCOME})
        elif path == "/api/reports/index":
            fulfill_json(
                route,
                {
                    "success": True,
                    "session_id": "public:wp4-browser-user:default",
                    "items": [
                        {
                            "report_id": REPORT_ID,
                            "session_id": "public:wp4-browser-user:default",
                            "ticker": "AAPL",
                            "title": "AAPL 证据化研究报告",
                            "summary": "真实行情与公开材料支持当前核心结论。",
                            "generated_at": "2026-07-15T08:30:00Z",
                            "quality_state": "pass",
                            "publishable": True,
                        }
                    ],
                    "count": 1,
                },
            )
        elif path == f"/api/reports/replay/{REPORT_ID}":
            fulfill_json(
                route,
                {
                    "success": True,
                    "session_id": "public:wp4-browser-user:default",
                    "report": report_payload(),
                    "citations": [],
                    "trace_digest": {},
                },
            )
        else:
            fulfill_json(route, {"success": True, "items": [], "data": {}})

    page.route(API_PATTERN, handler)
    return state


def prepare_page(page: Page, console_errors: list[str]) -> None:
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.add_init_script(
        """
        localStorage.setItem('finsight-rag-dev-auth-enabled', '1');
        localStorage.setItem('finsight-entry-mode', 'authenticated');
        localStorage.setItem('finsight-session-id', 'public:wp4-browser-user:default');
        sessionStorage.setItem('finsight-welcome-gate-passed', '1');
        """
    )
    install_api_mock(page)


def assert_viewport_integrity(page: Page) -> None:
    dimensions = page.evaluate(
        """() => ({
          viewport: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth
        })"""
    )
    assert dimensions["documentWidth"] <= dimensions["viewport"] + 1, dimensions
    assert dimensions["bodyWidth"] <= dimensions["viewport"] + 1, dimensions


def enter_dashboard(page: Page) -> None:
    page.goto(f"{BASE_URL}/welcome?from=%2Fdashboard%2FAAPL", wait_until="networkidle")
    page.get_by_role("button", name="继续进入").click()
    page.wait_for_url("**/dashboard/AAPL")
    page.locator('[data-testid="prediction-track"]').wait_for(state="visible")
    page.locator('[data-testid="prediction-empty-state"]').filter(has_text="尚未生成 AI 判断").wait_for()
    page.locator('[data-testid="prediction-generate"]').wait_for(state="visible")
    assert page.locator('[data-testid="prediction-generate"]').is_enabled()


def generate_prediction(page: Page) -> None:
    page.locator('[data-testid="prediction-generate"]').click()
    page.get_by_text("真实日线趋势、动量和近期证据共同支持偏多判断。").wait_for(timeout=8_000)
    page.get_by_text("openai_compatible / gpt-5.6-luna").wait_for()


def validate_desktop(page: Page) -> None:
    enter_dashboard(page)
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-dashboard-desktop-empty.png", full_page=True)

    generate_prediction(page)
    page.locator('[data-testid="dashboard-tab-technical"]').click()
    chart = page.locator('[data-testid="dashboard-primary-candlestick"]')
    chart.wait_for(state="visible")
    chart.get_by_text("AI 标注").wait_for()
    chart.locator("svg path, canvas").first.wait_for(state="attached", timeout=8_000)
    assert chart.locator("svg path").count() >= 5
    chart.scroll_into_view_if_needed()
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-dashboard-desktop-prediction.png", full_page=True)

    page.get_by_role("button", name="追问").click()
    page.wait_for_url("**/chat")
    chat_input = page.locator("#chat-input")
    chat_input.wait_for(state="visible")
    assert "AAPL" in chat_input.input_value()
    page.screenshot(path=EVIDENCE_DIR / "wp4-chat-desktop-handoff.png", full_page=True)

    page.locator('[data-testid="sidebar-nav-history"]').click()
    page.wait_for_url("**/history")
    page.locator('[data-testid="prediction-history-item"]').wait_for()
    page.get_by_text("目标达成").first.wait_for()
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-history-desktop-predictions.png", full_page=True)

    page.get_by_role("tab", name="Reports").click()
    page.locator('[data-testid="report-history-item"]').wait_for()
    page.get_by_text("AAPL 证据化研究报告", exact=True).last.wait_for()
    page.screenshot(path=EVIDENCE_DIR / "wp4-history-desktop-reports.png", full_page=True)


def validate_mobile(page: Page) -> None:
    enter_dashboard(page)
    generate_prediction(page)
    clipped_prices = page.locator('[data-testid="prediction-price-level-value"]').evaluate_all(
        "elements => elements.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.textContent)"
    )
    assert not clipped_prices, clipped_prices
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-dashboard-mobile-prediction.png", full_page=True)

    page.locator('[data-testid="dashboard-tab-technical"]').click()
    chart = page.locator('[data-testid="dashboard-primary-candlestick"]')
    chart.locator("svg path, canvas").first.wait_for(state="attached", timeout=8_000)
    assert chart.locator("svg path").count() >= 5
    chart.scroll_into_view_if_needed()
    page.screenshot(path=EVIDENCE_DIR / "wp4-dashboard-mobile-technical.png", full_page=True)

    page.locator('[data-testid="sidebar-nav-history"]').click()
    page.wait_for_url("**/history")
    page.locator('[data-testid="prediction-history-item"]').wait_for()
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-history-mobile-predictions.png", full_page=True)

    page.get_by_role("tab", name="Reports").click()
    page.locator('[data-testid="report-history-item"]').wait_for()
    page.get_by_text("AAPL 证据化研究报告", exact=True).last.wait_for()
    assert_viewport_integrity(page)
    page.screenshot(path=EVIDENCE_DIR / "wp4-history-mobile-reports.png", full_page=True)


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        prepare_page(desktop, errors)
        validate_desktop(desktop)
        desktop.close()

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        prepare_page(mobile, errors)
        validate_mobile(mobile)
        mobile.close()

        browser.close()

    assert not errors, "Browser console errors:\n" + "\n".join(errors)
    print("WP4 browser validation passed: desktop and mobile workflows are complete.")


if __name__ == "__main__":
    main()
