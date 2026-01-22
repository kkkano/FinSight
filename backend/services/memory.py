# -*- coding: utf-8 -*-
"""
Memory Service - 用户记忆与画像管理
负责持久化用户偏好、投资风格、历史关注等长期记忆
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    risk_tolerance: str = "medium"  # low, medium, high
    investment_style: str = "balanced"  # conservative, balanced, aggressive
    watchlist: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "risk_tolerance": self.risk_tolerance,
            "investment_style": self.investment_style,
            "watchlist": self.watchlist,
            "preferences": self.preferences,
            "last_active": self.last_active
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserProfile':
        return cls(
            user_id=data.get("user_id", "default"),
            risk_tolerance=data.get("risk_tolerance", "medium"),
            investment_style=data.get("investment_style", "balanced"),
            watchlist=data.get("watchlist", []),
            preferences=data.get("preferences", {}),
            last_active=data.get("last_active", datetime.now().isoformat())
        )

class MemoryService:
    """
    记忆服务
    目前使用简单的 JSON 文件存储，后续可迁移至 Redis/Postgres
    """

    def __init__(self, storage_path: str = "data/memory"):
        self.storage_path = storage_path
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)

    def _get_file_path(self, user_id: str) -> str:
        return os.path.join(self.storage_path, f"{user_id}.json")

    def get_user_profile(self, user_id: str) -> UserProfile:
        """获取用户画像，不存在则创建默认"""
        file_path = self._get_file_path(user_id)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return UserProfile.from_dict(data)
            except Exception as e:
                logger.info(f"[MemoryService] Error loading profile for {user_id}: {e}")
                return UserProfile(user_id=user_id)
        else:
            return UserProfile(user_id=user_id)

    def update_user_profile(self, profile: UserProfile) -> bool:
        """更新用户画像"""
        file_path = self._get_file_path(profile.user_id)
        profile.last_active = datetime.now().isoformat()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.info(f"[MemoryService] Error saving profile for {profile.user_id}: {e}")
            return False

    def add_to_watchlist(self, user_id: str, ticker: str) -> bool:
        """添加关注"""
        profile = self.get_user_profile(user_id)
        if ticker not in profile.watchlist:
            profile.watchlist.append(ticker)
            return self.update_user_profile(profile)
        return True

    def remove_from_watchlist(self, user_id: str, ticker: str) -> bool:
        """取消关注"""
        profile = self.get_user_profile(user_id)
        if ticker in profile.watchlist:
            profile.watchlist.remove(ticker)
            return self.update_user_profile(profile)
        return True

    def set_preference(self, user_id: str, key: str, value: Any) -> bool:
        """设置偏好"""
        profile = self.get_user_profile(user_id)
        profile.preferences[key] = value
        return self.update_user_profile(profile)