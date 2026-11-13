"""生产构建含 Service Worker 的首屏依赖检查；接口用本机协议夹具。"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend/test-results/m9-first-load"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bundle = next((ROOT / "frontend/dist/assets").glob("EChartRuntime-*.js"))
    seen = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.on("request", lambda request: seen.append(urlsplit(request.url).path))
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def api(route):
                body = {"ready": True, "features": {}, "models": [], "items": [], "count": 0,
                        "profile": {}, "conversation": {"messages": []}, "watchlist": []}
                if urlsplit(route.request.url).path.endswith("/benchmarks/us20-v1/track-record"):
                    body = {"enabled": False, "universe": {"version": "ui-contract", "tickers": []},
                        "coverage": {"batch_date": None, "expected": 0, "accepted": 0, "counts": {}, "attempts": 0, "last_update": None},
                        "summary": {"opportunities": 0, "predictions": 0, "settled": 0, "pending": 0, "failed": 0,
                            "missed": 0, "abstained": 0, "awaiting_data": 0, "batch_count": 0, "stock_count": 0},
                        "groups": [], "records": [], "daily_series": [],
                        "metadata": {"source": "ui-contract", "frequency": "trading_day", "horizon_sessions": 5,
                            "direction_threshold": .005, "drawdown_threshold": .03, "window_days": None}}
                route.fulfill(content_type="application/json", body=json.dumps(body))
            page.route("**/api/**", api)
            page.goto("http://127.0.0.1:4275/chat")
            page.wait_for_load_state("networkidle")
            assert not errors, errors
            assert page.get_by_role("heading", name="加载失败", exact=True).count() == 0
            initial_dom = page.locator("body").aria_snapshot()[:1200]
            page.evaluate("async () => { await navigator.serviceWorker.ready; }")
            initial = list(seen)
            assert not any("vendor-echarts-" in path or "EChartRuntime-" in path for path in initial), initial
            page.screenshot(path=str(OUTPUT / "initial.png"), full_page=True)
            await_path = "/assets/" + bundle.name
            page.evaluate("async path => { await import(path); }", await_path)
            page.wait_for_load_state("networkidle")
            assert any("vendor-echarts-" in path for path in seen)
            evidence = {"scope": "本机生产构建的网络依赖检查；包含真实Service Worker，API为协议夹具。",
                "initial_dom": initial_dom, "initial_requests": initial, "after_chart_module": seen,
                "service_worker_active": True, "initial_echarts_requests": 0, "chart_module_import_loads_echarts": True,
                "page_errors": errors}
            (OUTPUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"passed": 2, "evidence": str(OUTPUT / "evidence.json")}, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
