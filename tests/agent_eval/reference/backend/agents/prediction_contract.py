# -*- coding: utf-8 -*-
"""历史导入兼容入口；实现与缓存由中性宿主管理。"""
from __future__ import annotations

import sys

from backend.common import prediction_contract as _host

sys.modules[__name__] = _host
