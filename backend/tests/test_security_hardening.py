# -*- coding: utf-8 -*-
"""公网安全整改回归测试（2026-06-04）。

覆盖 5 个公网安全坑的修复：
1. /api/config 敏感字段（LLM 端点/凭据）写操作需内部 token，匿名拒绝
2. /api/subscriptions 不再 dump 全站 PII（email 必填，None 拒绝）
3. 限流伪造 IP 头绕过（TRUST_PROXY_HEADERS 开关）
4. /api/alerts/feed IDOR（无订阅邮箱拒绝读提醒历史）
5. 异常不泄露内部细节（detail 为通用消息，不含 str(exc)）
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.api import main as main_module  # noqa: E402
from backend.api.main import app  # noqa: E402
from backend.services import subscription_service as subs  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_rate_limiter(monkeypatch):
    """禁用全局限流单例。

    限流桶是模块级单例（同一 TestClient host 共享），多测试连发会累积触发 429，
    干扰安全断言。这里每个测试都替换为 enabled=False 的全新实例（monkeypatch
    自动还原），保证测试聚焦于安全逻辑本身。
    """
    monkeypatch.setattr(
        main_module,
        "_rate_limiter",
        main_module.SimpleRateLimiter(limit_per_window=10000, window_seconds=60, enabled=False),
    )


def _configure_test_storage(tmp_path: Any) -> None:
    subs.SUBSCRIPTIONS_FILE = tmp_path / "subscriptions_security_test.json"
    subs._subscription_service = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 坑 1：/api/config LLM 端点劫持
# ---------------------------------------------------------------------------


def test_config_sensitive_field_rejected_without_internal_token(tmp_path, monkeypatch):
    """匿名（无内部 token）写 llm_api_base/llm_api_key 必须被拒（403），即使 API_AUTH_ENABLED=false。"""
    from backend.api import config_router

    cfg_file = str(tmp_path / "user_config.json")
    monkeypatch.setattr(config_router, "USER_CONFIG_PATH", cfg_file)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("API_AUTH_KEYS", "internal-secret-1")

    with TestClient(app) as client:
        resp = client.post(
            "/api/config",
            json={"llm_api_base": "https://evil.attacker.example/v1", "llm_api_key": "stolen"},
        )

    assert resp.status_code == 403
    # 敏感字段绝不能落盘
    assert not os.path.exists(cfg_file) or "evil.attacker" not in open(cfg_file, encoding="utf-8").read()


def test_config_sensitive_field_accepted_with_internal_token(tmp_path, monkeypatch):
    """携带有效内部 token 时，敏感字段写操作放行。"""
    from backend.api import config_router

    cfg_file = str(tmp_path / "user_config.json")
    monkeypatch.setattr(config_router, "USER_CONFIG_PATH", cfg_file)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("API_AUTH_KEYS", "internal-secret-1")

    with TestClient(app) as client:
        resp = client.post(
            "/api/config",
            json={"llm_api_base": "https://my.endpoint.example/v1"},
            headers={"X-API-Key": "internal-secret-1"},
        )

    assert resp.status_code == 200
    assert resp.json().get("success") is True
    saved = json.load(open(cfg_file, encoding="utf-8"))
    assert saved.get("llm_api_base") == "https://my.endpoint.example/v1"


def test_config_public_field_writable_without_token(tmp_path, monkeypatch):
    """非敏感 UI 字段（theme/layout_mode）匿名也能写，不受守卫影响。"""
    from backend.api import config_router

    cfg_file = str(tmp_path / "user_config.json")
    monkeypatch.setattr(config_router, "USER_CONFIG_PATH", cfg_file)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("API_AUTH_KEYS", "internal-secret-1")

    with TestClient(app) as client:
        resp = client.post("/api/config", json={"theme": "dark", "layout_mode": "wide"})

    assert resp.status_code == 200
    saved = json.load(open(cfg_file, encoding="utf-8"))
    assert saved.get("theme") == "dark"
    assert saved.get("layout_mode") == "wide"


def test_config_rejects_sensitive_when_no_internal_token_configured(tmp_path, monkeypatch):
    """服务端未配置任何内部 token 时，敏感写操作一律拒绝（不能默默放行）。"""
    from backend.api import config_router

    cfg_file = str(tmp_path / "user_config.json")
    monkeypatch.setattr(config_router, "USER_CONFIG_PATH", cfg_file)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.delenv("API_AUTH_KEYS", raising=False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)

    with TestClient(app) as client:
        resp = client.post("/api/config", json={"llm_api_key": "x"})

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 坑 2：/api/subscriptions PII dump
# ---------------------------------------------------------------------------


def test_subscriptions_requires_email_no_dump(tmp_path, monkeypatch):
    """email 缺失时拒绝（400），绝不返回全站订阅。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()
    service.subscribe(email="victim@example.com", ticker="AAPL")
    service.subscribe(email="other@example.com", ticker="TSLA")

    with TestClient(app) as client:
        # 不带 email
        resp = client.get("/api/subscriptions")
        assert resp.status_code == 400

        # 空 email
        resp2 = client.get("/api/subscriptions", params={"email": "   "})
        assert resp2.status_code == 400


def test_subscriptions_email_returns_only_owner(tmp_path, monkeypatch):
    """带 email 时只返回该邮箱自己的订阅，不泄露他人。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()
    service.subscribe(email="victim@example.com", ticker="AAPL")
    service.subscribe(email="other@example.com", ticker="TSLA")

    with TestClient(app) as client:
        resp = client.get("/api/subscriptions", params={"email": "victim@example.com"})

    assert resp.status_code == 200
    data = resp.json()
    tickers = {s["ticker"] for s in data.get("subscriptions") or []}
    assert tickers == {"AAPL"}
    assert "TSLA" not in tickers


def test_subscription_service_email_none_with_include_all_false_returns_empty(tmp_path):
    """service 纵深防御：email=None + include_all=False 永远返回空列表。"""
    _configure_test_storage(tmp_path)
    service = subs.get_subscription_service()
    service.subscribe(email="a@example.com", ticker="AAPL")

    assert service.get_subscriptions(email=None, include_all=False) == []
    # 内部调度器（默认 None）仍可拿到全量（保持调度器行为）
    assert len(service.get_subscriptions()) == 1


# ---------------------------------------------------------------------------
# 坑 3：限流伪造 IP 头绕过
# ---------------------------------------------------------------------------


def test_client_ip_ignores_proxy_headers_when_trust_disabled(monkeypatch):
    """TRUST_PROXY_HEADERS=false 时忽略 CF/XFF 头，回退连接对端 IP（防伪造头绕过限流）。"""
    import backend.api.main as main_module

    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")

    request = MagicMock()
    request.headers = {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
    request.client.host = "172.18.0.5"

    # 不信任头 → 用真实连接对端，攻击者换头无效
    assert main_module._resolve_client_ip(request) == "172.18.0.5"


def test_client_ip_trusts_proxy_headers_by_default(monkeypatch):
    """默认（未设置）信任代理头，保持线上 Cloudflare 部署行为不变。"""
    import backend.api.main as main_module

    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)

    request = MagicMock()
    request.headers = {"CF-Connecting-IP": "1.2.3.4"}
    request.client.host = "172.18.0.5"

    assert main_module._resolve_client_ip(request) == "1.2.3.4"


# ---------------------------------------------------------------------------
# 坑 4：/api/alerts/feed IDOR
# ---------------------------------------------------------------------------


def test_alert_feed_rejects_email_without_subscription(tmp_path, monkeypatch):
    """无订阅的邮箱不允许读提醒历史（防 IDOR / 邮箱枚举），返回 404。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()
    service.subscribe(email="real@example.com", ticker="AAPL")

    with TestClient(app) as client:
        # 攻击者构造他人/随机邮箱，但该邮箱无订阅 → 拒绝
        resp = client.get("/api/alerts/feed", params={"email": "stranger@example.com"})

    assert resp.status_code == 404


def test_alert_feed_allows_owner_with_subscription(tmp_path, monkeypatch):
    """有订阅的邮箱可正常读自己的提醒历史。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()
    service.subscribe(email="real@example.com", ticker="AAPL")
    service.record_alert_event(
        "real@example.com",
        "AAPL",
        "price_change",
        severity="high",
        title="AAPL move",
        message="AAPL +4%",
    )

    with TestClient(app) as client:
        resp = client.get("/api/alerts/feed", params={"email": "real@example.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["count"] == 1


# ---------------------------------------------------------------------------
# 坑 5：异常不泄露内部细节
# ---------------------------------------------------------------------------


def test_subscriptions_internal_error_not_leaked(tmp_path, monkeypatch):
    """service 抛内部异常时，对外只返回通用消息，不含原始 str(exc)。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()

    def _boom(*args, **kwargs):
        raise RuntimeError("INTERNAL_SECRET_PATH /opt/secret/db.sqlite traceback")

    monkeypatch.setattr(service, "get_subscriptions", _boom)

    with TestClient(app) as client:
        resp = client.get("/api/subscriptions", params={"email": "user@example.com"})

    assert resp.status_code == 500
    detail = str(resp.json().get("detail", ""))
    # 通用消息，绝不泄露内部路径 / 异常文本
    assert detail == "处理失败，请稍后重试"
    assert "INTERNAL_SECRET_PATH" not in detail
    assert "traceback" not in detail.lower()


def test_alert_feed_internal_error_not_leaked(tmp_path, monkeypatch):
    """alerts feed 内部异常同样脱敏。"""
    _configure_test_storage(tmp_path)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    service = subs.get_subscription_service()
    service.subscribe(email="real@example.com", ticker="AAPL")

    def _boom(*args, **kwargs):
        raise RuntimeError("DB_DSN postgresql://user:pass@host/db leaked")

    monkeypatch.setattr(service, "list_alert_events", _boom)

    with TestClient(app) as client:
        resp = client.get("/api/alerts/feed", params={"email": "real@example.com"})

    assert resp.status_code == 500
    detail = str(resp.json().get("detail", ""))
    assert detail == "处理失败，请稍后重试"
    assert "postgresql://" not in detail
