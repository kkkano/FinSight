#!/usr/bin/env python3
"""
订阅管理服务
管理用户的股票订阅和提醒
"""

import logging

logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-


import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import re

# 订阅数据存储文件
SUBSCRIPTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "subscriptions.json"
ALERT_FAILURE_LIMIT = int(os.getenv("ALERT_FAILURE_LIMIT", "3"))
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class SubscriptionService:
    """订阅管理服务"""
    
    def __init__(self):
        self.subscriptions_file = SUBSCRIPTIONS_FILE
        self.subscriptions_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_subscriptions()
    
    def _load_subscriptions(self):
        """加载订阅数据"""
        if self.subscriptions_file.exists():
            try:
                with open(self.subscriptions_file, 'r', encoding='utf-8') as f:
                    self.subscriptions = json.load(f)
            except Exception as e:
                logger.info(f"⚠️  加载订阅数据失败: {e}")
                self.subscriptions = {}
        else:
            self.subscriptions = {}
    
    def _save_subscriptions(self):
        """保存订阅数据"""
        try:
            with open(self.subscriptions_file, 'w', encoding='utf-8') as f:
                json.dump(self.subscriptions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.info(f"❌ 保存订阅数据失败: {e}")
    
    def subscribe(
        self,
        email: str,
        ticker: str,
        alert_types: List[str] = None,
        price_threshold: Optional[float] = None
    ) -> bool:
        """
        订阅股票提醒
        
        Args:
            email: 用户邮箱
            ticker: 股票代码
            alert_types: 提醒类型列表（price_change, news, report）
            price_threshold: 价格变动阈值（百分比）
            
        Returns:
            是否订阅成功
        """
        if alert_types is None:
            alert_types = ["price_change", "news"]

        if not self.is_valid_email(email):
            logger.info(f"❌ Invalid email address: {email}")
            return False
        
        if email not in self.subscriptions:
            self.subscriptions[email] = []
        
        # 检查是否已订阅
        for sub in self.subscriptions[email]:
            if sub['ticker'] == ticker:
                # 更新现有订阅
                sub['alert_types'] = alert_types
                sub['price_threshold'] = price_threshold
                sub['updated_at'] = datetime.now().isoformat()
                self._save_subscriptions()
                return True
        
        # 添加新订阅
        subscription = {
            "email": email,
            "ticker": ticker,
            "alert_types": alert_types,
            "price_threshold": price_threshold,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_alert_at": None,
            "last_news_at": None,
            "last_alert_attempt_at": None,
            "last_alert_error": None,
            "last_alert_error_at": None,
            "alert_failures": 0,
            "disabled": False,
        }
        
        self.subscriptions[email].append(subscription)
        self._save_subscriptions()
        
        logger.info(f"✅ 用户 {email} 已订阅 {ticker}")
        return True

    def is_valid_email(self, email: str) -> bool:
        """Basic email format validation."""
        if not email or "@" not in email:
            return False
        return bool(EMAIL_REGEX.match(email))
    
    def unsubscribe(self, email: str, ticker: Optional[str] = None) -> bool:
        """
        取消订阅
        
        Args:
            email: 用户邮箱
            ticker: 股票代码（如果为 None，取消所有订阅）
            
        Returns:
            是否取消成功
        """
        if email not in self.subscriptions:
            return False
        
        if ticker is None:
            # 取消所有订阅
            del self.subscriptions[email]
        else:
            # 取消特定股票的订阅
            self.subscriptions[email] = [
                sub for sub in self.subscriptions[email]
                if sub['ticker'] != ticker
            ]
            
            # 如果该邮箱没有其他订阅，删除邮箱记录
            if not self.subscriptions[email]:
                del self.subscriptions[email]
        
        self._save_subscriptions()
        logger.info(f"✅ 用户 {email} 已取消订阅 {ticker or '所有股票'}")
        return True
    
    def get_subscriptions(self, email: Optional[str] = None) -> List[Dict]:
        """
        获取订阅列表
        
        Args:
            email: 用户邮箱（如果为 None，返回所有订阅）
            
        Returns:
            订阅列表
        """
        if email is None:
            # 返回所有订阅
            all_subs = []
            for email_key, subs in self.subscriptions.items():
                all_subs.extend(subs)
            return all_subs
        else:
            return self.subscriptions.get(email, [])
    
    def get_subscribers_for_ticker(self, ticker: str) -> List[Dict]:
        """
        获取订阅特定股票的所有用户
        
        Args:
            ticker: 股票代码
            
        Returns:
            订阅列表
        """
        subscribers = []
        for email, subs in self.subscriptions.items():
            for sub in subs:
                if sub['ticker'] == ticker:
                    subscribers.append(sub)
        return subscribers
    
    def update_last_alert(self, email: str, ticker: str):
        """更新最后提醒时间"""
        if email in self.subscriptions:
            for sub in self.subscriptions[email]:
                if sub['ticker'] == ticker:
                    sub['last_alert_at'] = datetime.now().isoformat()
                    self._save_subscriptions()
                    break

    def record_alert_attempt(self, email: str, ticker: str, success: bool, error: Optional[str] = None, disable: bool = False):
        """Record alert delivery attempt and optionally disable subscription."""
        if email in self.subscriptions:
            for sub in self.subscriptions[email]:
                if sub['ticker'] == ticker:
                    now = datetime.now().isoformat()
                    sub['last_alert_attempt_at'] = now
                    if success:
                        sub['last_alert_at'] = now
                        sub['alert_failures'] = 0
                        sub['last_alert_error'] = None
                        sub['last_alert_error_at'] = None
                        sub['disabled'] = False
                    else:
                        sub['alert_failures'] = int(sub.get('alert_failures', 0)) + 1
                        sub['last_alert_error'] = error
                        sub['last_alert_error_at'] = now
                        if disable or sub['alert_failures'] >= ALERT_FAILURE_LIMIT:
                            sub['disabled'] = True
                    self._save_subscriptions()
                    break

    def update_last_news(self, email: str, ticker: str):
        """更新最后新闻提醒时间"""
        if email in self.subscriptions:
            for sub in self.subscriptions[email]:
                if sub['ticker'] == ticker:
                    sub['last_news_at'] = datetime.now().isoformat()
                    self._save_subscriptions()
                    break


# 全局实例
_subscription_service = None

def get_subscription_service() -> SubscriptionService:
    """获取订阅服务实例（单例模式）"""
    global _subscription_service
    if _subscription_service is None:
        _subscription_service = SubscriptionService()
    return _subscription_service
