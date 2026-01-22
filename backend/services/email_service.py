#!/usr/bin/env python3
"""
邮件服务模块
用于发送股票提醒邮件
"""

import logging

logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-


import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

# 邮件配置（从环境变量读取）
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)


class EmailService:
    """邮件服务类"""
    
    def __init__(self):
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
        text_content: Optional[str] = None
    ) -> bool:
        """
        发送邮件
        
        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            html_content: HTML 内容
            text_content: 纯文本内容（可选）
            
        Returns:
            是否发送成功
        """
        if not self.smtp_user or not self.smtp_password:
            logger.info("⚠️  邮件服务未配置：请设置 SMTP_USER 和 SMTP_PASSWORD 环境变量")
            return False
        
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['From'] = self.email_from
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # 添加文本和HTML内容
            if text_content:
                part1 = MIMEText(text_content, 'plain', 'utf-8')
                msg.attach(part1)
            
            part2 = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(part2)
            
            # 发送邮件
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            # 使用纯 ASCII 日志，避免控制台编码问题
            logger.info(f"[EmailService] Sent email to {to_email}")
            return True
            
        except Exception as e:
            logger.info(f"[EmailService] Failed to send email: {e}")
            return False
    
    def send_stock_alert(
        self,
        to_email: str,
        ticker: str,
        alert_type: str,
        message: str,
        current_price: Optional[float] = None,
        change_percent: Optional[float] = None
    ) -> bool:
        """
        发送股票提醒邮件
        
        Args:
            to_email: 收件人邮箱
            ticker: 股票代码
            alert_type: 提醒类型（price_change, news, report）
            message: 提醒消息
            current_price: 当前价格
            change_percent: 涨跌幅
            
        Returns:
            是否发送成功
        """
        # 根据提醒类型生成主题
        if alert_type == "price_change":
            subject = f"📊 {ticker} 价格变动提醒"
        elif alert_type == "news":
            subject = f"📰 {ticker} 重要新闻提醒"
        elif alert_type == "report":
            subject = f"📈 {ticker} 分析报告提醒"
        else:
            subject = f"🔔 {ticker} 提醒"
        
        # 生成HTML内容
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
                    {f'<div class="price">当前价格: ${current_price:.2f}</div>' if current_price else ''}
                    {f'<div class="change {"positive" if change_percent and change_percent >= 0 else "negative"}">涨跌幅: {change_percent:+.2f}%</div>' if change_percent is not None else ''}
                    <div class="message">
                        <p>{message}</p>
                    </div>
                    <div class="footer">
                        <p>此邮件由 FinSight AI 自动发送</p>
                        <p>发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # 生成纯文本内容
        text_content = f"""
FinSight 股票提醒

股票代码: {ticker}
{f'当前价格: ${current_price:.2f}' if current_price else ''}
{f'涨跌幅: {change_percent:+.2f}%' if change_percent is not None else ''}

{message}

---
此邮件由 FinSight AI 自动发送
发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        return self.send_email(to_email, subject, html_content, text_content)


# 全局实例
_email_service = None

def get_email_service() -> EmailService:
    """获取邮件服务实例（单例模式）"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service