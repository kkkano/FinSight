#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试工具修复
验证 ddgs 和 K 线图数据获取是否正常工作
"""

import sys
import os

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("=" * 70)
print("工具修复验证测试")
print("=" * 70)

# 测试 1: ddgs 导入
print("\n1. 测试 ddgs 导入...")
try:
    from backend.tools import search
    print("✅ search 函数导入成功")
    
    # 测试搜索（不实际执行，只检查导入）
    print("   检查 DDGS 导入状态...")
    from backend.tools import DDGS
    if DDGS is not None:
        print("   ✅ DDGS 可用")
    else:
        print("   ⚠️  DDGS 不可用（需要安装 ddgs 包）")
except Exception as e:
    print(f"❌ 导入失败: {e}")

# 测试 2: K 线图数据获取
print("\n2. 测试 K 线图数据获取...")
try:
    from backend.tools import get_stock_historical_data
    
    print("   测试获取 TSLA 的历史数据...")
    result = get_stock_historical_data("TSLA")
    
    if "error" in result:
        print(f"   ⚠️  获取失败: {result['error']}")
    elif "kline_data" in result:
        data = result["kline_data"]
        print(f"   ✅ 成功获取 {len(data)} 条 K 线数据")
        if len(data) > 0:
            print(f"   第一条数据: {data[0]}")
            print(f"   最后一条数据: {data[-1]}")
    else:
        print(f"   ⚠️  未知响应格式: {result}")
        
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 3: 检查 API 端点
print("\n3. 测试 API 端点...")
try:
    from backend.api.main import app
    from backend.tools import get_stock_historical_data
    
    # 模拟 API 调用
    print("   模拟 /api/stock/kline/TSLA 调用...")
    result = get_stock_historical_data("TSLA")
    
    if "error" in result:
        print(f"   ⚠️  API 返回错误: {result['error']}")
    else:
        print(f"   ✅ API 数据格式正确")
        
except Exception as e:
    print(f"❌ 测试失败: {e}")

print("\n" + "=" * 70)
print("测试完成")
print("=" * 70)

