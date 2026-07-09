# -*- coding: utf-8 -*-
"""DEPRECATED shim（WP3-T7 / BE-07）：rebalance schema 已下沉 backend/services/rebalance/schemas.py。
api → services 的依赖方向就此恢复正确。保留到 WP3 Task 8 统一删除。"""
from backend.services.rebalance.schemas import *  # noqa: F401,F403
