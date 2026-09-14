from __future__ import annotations

from unittest.mock import MagicMock

from backend.api import security_gate as security_gate_module


def test_client_ip_ignores_proxy_headers_when_trust_disabled(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    request = MagicMock()
    request.headers = {
        "CF-Connecting-IP": "1.2.3.4",
        "X-Forwarded-For": "5.6.7.8",
    }
    request.client.host = "172.18.0.5"

    assert security_gate_module._resolve_client_ip(request) == "172.18.0.5"


def test_client_ip_trusts_proxy_headers_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    request = MagicMock()
    request.headers = {"CF-Connecting-IP": "1.2.3.4"}
    request.client.host = "172.18.0.5"

    assert security_gate_module._resolve_client_ip(request) == "1.2.3.4"
