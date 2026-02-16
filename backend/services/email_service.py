#!/usr/bin/env python3
"""
邮件服务模块
用于发送股票提醒邮件
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# 邮件配置（从环境变量读取）
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)


class EmailService:
    """邮件服务类"""

    def __init__(self) -> None:
        self.smtp_server = SMTP_SERVER
        self.smtp_port = SMTP_PORT
        self.smtp_user = SMTP_USER
        self.smtp_password = SMTP_PASSWORD
        self.email_from = EMAIL_FROM

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """
        发送邮件

        Returns:
            (success, error_type, error_message)
            error_type: 'none' | 'transient' | 'permanent'
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("⚠️ 邮件服务未配置：请设置 SMTP_USER 和 SMTP_PASSWORD 环境变量")
            return False, "permanent", "SMTP credentials missing"

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.email_from
            msg["To"] = to_email
            msg["Subject"] = subject

            if text_content:
                msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("[EmailService] Sent email to %s", to_email)
            return True, "none", None

        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, ConnectionError) as exc:
            logger.error("[EmailService] Transient network error for %s: %s", to_email, exc)
            return False, "transient", str(exc)
        except (
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError,
        ) as exc:
            logger.error("[EmailService] Permanent SMTP error for %s: %s", to_email, exc)
            return False, "permanent", str(exc)
        except Exception as exc:  # noqa: BLE001 - 保持外部接口兼容
            logger.error("[EmailService] Unexpected error for %s: %s", to_email, exc)
            return False, "transient", str(exc)

    def send_stock_alert(
        self,
        to_email: str,
        ticker: str,
        alert_type: str,
        message: str,
        current_price: Optional[float] = None,
        change_percent: Optional[float] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """
        发送股票提醒邮件
        """
        if alert_type == "price_change":
            subject = f"📊 {ticker} 价格变动提醒"
        elif alert_type == "news":
            subject = f"📰 {ticker} 重要新闻提醒"
        elif alert_type == "report":
            subject = f"📈 {ticker} 分析报告提醒"
        elif alert_type == "risk":
            subject = f"⚠️ {ticker} 风险等级变动提醒"
        else:
            subject = f"🔔 {ticker} 提醒"

        change_class = "positive" if change_percent is not None and change_percent >= 0 else "negative"
        price_html = f'<div class="price">当前价格: ${current_price:.2f}</div>' if current_price is not None else ""
        change_html = (
            f'<div class="change {change_class}">涨跌幅: {change_percent:+.2f}%</div>'
            if change_percent is not None
            else ""
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border-radius: 0 0 5px 5px; }}
                .ticker {{ font-size: 24px; font-weight: bold; color: #2196F3; }}
                .price {{ font-size: 20px; margin: 10px 0; }}
                .change {{ font-size: 18px; font-weight: bold; }}
                .change.positive {{ color: #4CAF50; }}
                .change.negative {{ color: #f44336; }}
                .message {{ margin: 20px 0; padding: 15px; background-color: white; border-left: 4px solid #2196F3; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>FinSight 股票提醒</h1>
                </div>
                <div class="content">
                    <div class="ticker">{ticker}</div>
                    {price_html}
                    {change_html}
                    <div class="message">
                        <p>{message}</p>
                    </div>
                    <div class="footer">
                        <p>此邮件由 FinSight AI 自动发送</p>
                        <p>发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        price_text = f"当前价格: ${current_price:.2f}" if current_price is not None else ""
        change_text = f"涨跌幅: {change_percent:+.2f}%" if change_percent is not None else ""
        text_content = f"""
FinSight 股票提醒

股票代码: {ticker}
{price_text}
{change_text}

{message}

---
此邮件由 FinSight AI 自动发送
发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        """

        return self.send_email(to_email, subject, html_content, text_content)


_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """获取邮件服务实例（单例模式）"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service

