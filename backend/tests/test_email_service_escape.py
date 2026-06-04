# -*- coding: utf-8 -*-
"""P3: 邮件 HTML 转义测试

验证 ticker / message 等用户/agent 可控内容直插 HTML body 前被正确转义，
防止 HTML/脚本注入。
"""

from unittest.mock import patch

from backend.services.email_service import EmailService


def _capture_html(svc: EmailService, **kwargs) -> str:
    """调用 send_stock_alert，截获传给 send_email 的 html_content。"""
    captured: dict[str, str] = {}

    def fake_send(to_email, subject, html_content, text_content=None):
        captured["html"] = html_content
        return True, "none", None

    with patch.object(svc, "send_email", side_effect=fake_send):
        svc.send_stock_alert(**kwargs)
    return captured.get("html", "")


def test_message_html_is_escaped():
    svc = EmailService()
    html_out = _capture_html(
        svc,
        to_email="x@example.com",
        ticker="AAPL",
        alert_type="news",
        message='<script>alert("xss")</script>',
    )
    # 原始脚本标签不得出现
    assert "<script>" not in html_out
    # 应被转义
    assert "&lt;script&gt;" in html_out


def test_ticker_html_is_escaped():
    svc = EmailService()
    html_out = _capture_html(
        svc,
        to_email="x@example.com",
        ticker='<img src=x onerror=alert(1)>',
        alert_type="price_change",
        message="normal",
    )
    assert "<img" not in html_out
    assert "&lt;img" in html_out


def test_normal_content_still_rendered():
    svc = EmailService()
    html_out = _capture_html(
        svc,
        to_email="x@example.com",
        ticker="TSLA",
        alert_type="report",
        message="价格突破阻力位",
    )
    assert "TSLA" in html_out
    assert "价格突破阻力位" in html_out
