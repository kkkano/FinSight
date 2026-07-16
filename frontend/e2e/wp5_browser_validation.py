from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, Route, sync_playwright

from wp4_browser_validation import (
    BASE_URL,
    assert_viewport_integrity,
    dashboard_payload,
    fulfill_json,
    install_api_mock,
)


EVIDENCE_DIR = Path(__file__).resolve().parents[2] / ".omx" / "evidence" / "wp5"
API_ORIGIN = "http://127.0.0.1:8000"
SESSION_ID = "user:wp5-browser-user:default"


def monitor_comment(symbol: str) -> dict[str, object]:
    normalized = symbol.strip().upper()
    return {
        "id": f"comment-{normalized.lower()}",
        "session_id": SESSION_ID,
        "symbol": normalized,
        "ts": "2026-07-15T15:40:00Z",
        "level": "alert",
        "text": f"{normalized} 突破当前 Prediction 关键价位，已进入重估队列。",
        "trigger": {
            "kind": "prediction_level_break",
            "detail": "价格突破目标区间上沿",
            "observed_at": "2026-07-15T15:40:00Z",
        },
        "source": "agent",
        "escalated": True,
        "prediction_id": "11111111-1111-4111-8111-111111111111",
        "chart_url": f"/dashboard/{normalized}?prediction=11111111-1111-4111-8111-111111111111",
    }


class SseState:
    def __init__(self) -> None:
        self.streams: list[dict[str, str]] = []
        self.stop = threading.Event()


def start_sse_server(state: SseState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin") or BASE_URL
            requested = self.headers.get("Access-Control-Request-Headers")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                requested or "authorization, content-type",
            )
            self.send_header("Access-Control-Max-Age", "600")

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self.send_response(204)
            self._cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            parsed = urlparse(self.path)
            if parsed.path != "/api/monitor/comments/stream":
                self.send_error(404)
                return

            query = parse_qs(parsed.query)
            symbol = str((query.get("symbol") or [""])[0]).strip().upper()
            session_id = str((query.get("session_id") or [""])[0]).strip()
            state.streams.append({"symbol": symbol, "session_id": session_id})

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            snapshot = json.dumps([monitor_comment(symbol)], ensure_ascii=False)
            first_frame = f"event: snapshot\nid: snapshot-{symbol}\ndata: {snapshot}\n\n"
            try:
                self.wfile.write(first_frame.encode("utf-8"))
                self.wfile.flush()
                while not state.stop.wait(0.25):
                    self.wfile.write(b"event: heartbeat\ndata: {}\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            finally:
                self.close_connection = True

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def dynamic_dashboard_payload(page: Page) -> dict[str, object]:
    payload = deepcopy(dashboard_payload())
    path = urlparse(page.url).path
    symbol = path.rsplit("/", 1)[-1].strip().upper() if "/dashboard/" in path else "AAPL"
    if symbol not in {"AAPL", "MSFT"}:
        symbol = "AAPL"
    payload["state"]["active_asset"] = {
        "symbol": symbol,
        "type": "equity",
        "display_name": "Apple Inc." if symbol == "AAPL" else "Microsoft Corp.",
    }
    payload["state"]["watchlist"] = [
        {"symbol": "AAPL", "type": "equity", "name": "Apple"},
        {"symbol": "MSFT", "type": "equity", "name": "Microsoft"},
    ]
    return payload


def install_wp5_mocks(page: Page, request_state: dict[str, list[dict[str, str]]]) -> None:
    install_api_mock(page)

    def dashboard_handler(route: Route) -> None:
        if urlparse(route.request.url).path != "/api/dashboard":
            route.fallback()
            return
        fulfill_json(route, dynamic_dashboard_payload(page))

    def monitor_handler(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        if parsed.path == "/api/monitor/comments/stream":
            route.continue_()
            return

        if parsed.path == "/api/monitor/leases" and request.method == "POST":
            payload = request.post_data_json or {}
            symbol = str(payload.get("symbol") or "").strip().upper()
            session_id = str(payload.get("session_id") or "").strip()
            lease_id = f"lease-{symbol.lower()}"
            request_state["acquires"].append(
                {"id": lease_id, "symbol": symbol, "session_id": session_id}
            )
            fulfill_json(
                route,
                {
                    "lease": {
                        "id": lease_id,
                        "session_id": session_id,
                        "symbol": symbol,
                        "lease_token": f"token-{symbol.lower()}",
                        "expires_at": "2026-07-15T16:00:00Z",
                    }
                },
            )
            return

        if parsed.path.startswith("/api/monitor/leases/") and request.method == "DELETE":
            request_state["releases"].append(
                {"id": parsed.path.rsplit("/", 1)[-1], "method": request.method}
            )
            fulfill_json(route, {"success": True})
            return

        if parsed.path.startswith("/api/monitor/leases/") and request.method == "PUT":
            request_state["renews"].append(
                {"id": parsed.path.rsplit("/", 1)[-1], "method": request.method}
            )
            fulfill_json(route, {"success": True})
            return

        request_state["other"].append({"path": parsed.path, "method": request.method})
        route.fallback()

    page.route(f"{API_ORIGIN}/api/dashboard**", dashboard_handler)
    page.route(f"{API_ORIGIN}/api/monitor/**", monitor_handler)


def prepare_authenticated_page(
    page: Page,
    console_errors: list[str],
    request_state: dict[str, list[dict[str, str]]],
) -> None:
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.add_init_script(
        """
        localStorage.setItem('finsight-entry-mode', 'authenticated');
        sessionStorage.setItem('finsight-welcome-gate-passed', '1');
        """
    )
    install_wp5_mocks(page, request_state)


def prepare_anonymous_page(
    page: Page,
    console_errors: list[str],
    request_state: dict[str, list[dict[str, str]]],
) -> None:
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.add_init_script(
        """
        localStorage.setItem('finsight-entry-mode', 'anonymous');
        sessionStorage.setItem('finsight-welcome-gate-passed', '1');
        """
    )
    install_wp5_mocks(page, request_state)


def wait_for_feed(
    page: Page,
    symbol: str,
    *,
    diagnostics: dict[str, object] | None = None,
) -> None:
    feed = page.locator('[data-testid="monitor-activity-feed"]')
    feed.wait_for(state="visible")
    try:
        feed.get_by_text(f"{symbol} 突破当前 Prediction 关键价位，已进入重估队列。").wait_for(
            timeout=8_000
        )
    except Exception as exc:
        details = {
            "url": page.url,
            "feed": feed.inner_text(),
            **(diagnostics or {}),
        }
        raise AssertionError(f"Monitor feed did not receive {symbol}: {details}") from exc


def assert_feed_bounds(page: Page) -> None:
    result = page.locator('[data-testid="monitor-activity-feed"]').evaluate(
        """element => {
          const box = element.getBoundingClientRect();
          const children = [...element.querySelectorAll('*')];
          return {
            box,
            overflow: children
              .map(child => child.getBoundingClientRect())
              .filter(child => child.width > 0 && (child.left < box.left - 1 || child.right > box.right + 1))
              .map(child => child.textContent)
          };
        }"""
    )
    assert not result["overflow"], result


def enter_dashboard(page: Page) -> None:
    page.goto(f"{BASE_URL}/dashboard/AAPL", wait_until="domcontentloaded")
    page.locator('[data-testid="monitor-activity-feed"]').wait_for(state="visible")


def validate_authenticated_desktop(
    page: Page,
    request_state: dict[str, list[dict[str, str]]],
    sse_state: SseState,
) -> None:
    enter_dashboard(page)
    wait_for_feed(
        page,
        "AAPL",
        diagnostics={"requests": request_state, "streams": sse_state.streams},
    )
    assert_viewport_integrity(page)
    assert_feed_bounds(page)
    assert any(item["symbol"] == "AAPL" for item in request_state["acquires"])
    assert any(item["symbol"] == "AAPL" for item in sse_state.streams)
    page.screenshot(path=EVIDENCE_DIR / "wp5-monitor-desktop-aapl.png", full_page=True)

    page.evaluate(
        """() => {
          window.history.pushState({}, '', '/dashboard/MSFT');
          window.dispatchEvent(new PopStateEvent('popstate'));
        }"""
    )
    page.wait_for_url("**/dashboard/MSFT")
    wait_for_feed(
        page,
        "MSFT",
        diagnostics={"requests": request_state, "streams": sse_state.streams},
    )
    feed = page.locator('[data-testid="monitor-activity-feed"]')
    assert feed.get_by_text("AAPL 突破当前 Prediction 关键价位", exact=False).count() == 0
    assert any(item["symbol"] == "MSFT" for item in request_state["acquires"])
    assert any(item["id"] == "lease-aapl" for item in request_state["releases"])
    assert any(item["symbol"] == "MSFT" for item in sse_state.streams)
    assert_viewport_integrity(page)
    assert_feed_bounds(page)
    page.screenshot(path=EVIDENCE_DIR / "wp5-monitor-desktop-msft.png", full_page=True)


def validate_authenticated_mobile(page: Page) -> None:
    enter_dashboard(page)
    wait_for_feed(page, "AAPL")
    assert_viewport_integrity(page)
    assert_feed_bounds(page)
    page.locator('[data-testid="monitor-activity-feed"]').scroll_into_view_if_needed()
    page.screenshot(path=EVIDENCE_DIR / "wp5-monitor-mobile-aapl.png", full_page=True)


def validate_anonymous(
    page: Page,
    request_state: dict[str, list[dict[str, str]]],
    sse_state: SseState,
) -> None:
    stream_count = len(sse_state.streams)
    enter_dashboard(page)
    feed = page.locator('[data-testid="monitor-activity-feed"]')
    feed.get_by_text("匿名模式不会启动实时 AI 监控。").wait_for()
    page.wait_for_timeout(500)
    assert request_state["acquires"] == []
    assert request_state["releases"] == []
    assert len(sse_state.streams) == stream_count
    assert_viewport_integrity(page)
    assert_feed_bounds(page)
    page.screenshot(path=EVIDENCE_DIR / "wp5-monitor-anonymous.png", full_page=True)


def request_state() -> dict[str, list[dict[str, str]]]:
    return {"acquires": [], "releases": [], "renews": [], "other": []}


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    sse_state = SseState()
    server = start_sse_server(sse_state)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            desktop_state = request_state()
            desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
            prepare_authenticated_page(desktop, errors, desktop_state)
            validate_authenticated_desktop(desktop, desktop_state, sse_state)
            desktop.close()

            mobile_state = request_state()
            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            prepare_authenticated_page(mobile, errors, mobile_state)
            validate_authenticated_mobile(mobile)
            mobile.close()

            anonymous_state = request_state()
            anonymous = browser.new_page(viewport={"width": 390, "height": 844})
            prepare_anonymous_page(anonymous, errors, anonymous_state)
            validate_anonymous(anonymous, anonymous_state, sse_state)
            anonymous.close()

            browser.close()
    finally:
        sse_state.stop.set()
        server.shutdown()
        server.server_close()
        time.sleep(0.05)

    assert not errors, "Browser console errors:\n" + "\n".join(errors)
    print("WP5 browser validation passed: lease, stream isolation, mobile layout and anonymous zero-I/O.")


if __name__ == "__main__":
    main()
