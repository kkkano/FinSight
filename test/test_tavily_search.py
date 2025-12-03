#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 Tavily Search 集成
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 测试 Tavily Search
def test_tavily_search():
    """测试 Tavily Search 功能"""
    print("=" * 70)
    print("测试 Tavily Search 集成")
    print("=" * 70)
    
    # 检查 API Key
    tavily_api_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_api_key:
        print("⚠️  警告: 未找到 TAVILY_API_KEY 环境变量")
        print("   请访问 https://tavily.com 获取 API Key")
        print("   然后在 .env 文件中添加: TAVILY_API_KEY=your_api_key")
        print("\n   将回退到 DuckDuckGo 搜索...")
    else:
        print(f"✅ 找到 TAVILY_API_KEY: {tavily_api_key[:10]}...")
    
    # 测试导入
    print("\n1. 测试模块导入...")
    try:
        from backend.tools import search, TAVILY_AVAILABLE, TAVILY_API_KEY
        print(f"   ✅ 成功导入 search 函数")
        print(f"   ✅ TAVILY_AVAILABLE: {TAVILY_AVAILABLE}")
        print(f"   ✅ TAVILY_API_KEY 已配置: {bool(TAVILY_API_KEY)}")
    except Exception as e:
        print(f"   ❌ 导入失败: {e}")
        return False
    
    # 测试搜索功能
    print("\n2. 测试搜索功能...")
    test_queries = [
        "纳斯达克指数最新动态",
        "AAPL stock price today",
        "Tesla latest news"
    ]
    
    for query in test_queries:
        print(f"\n   查询: {query}")
        try:
            result = search(query)
            if result:
                # 显示前200个字符
                preview = result[:200] + "..." if len(result) > 200 else result
                print(f"   ✅ 搜索成功")
                print(f"   结果预览: {preview}")
                
                # 检查是否使用了 Tavily
                if "AI摘要" in result or "相关性:" in result:
                    print("   📊 使用了 Tavily AI 搜索")
                elif "DuckDuckGo" in result:
                    print("   🔍 使用了 DuckDuckGo 搜索（回退）")
            else:
                print("   ⚠️  搜索返回空结果")
        except Exception as e:
            print(f"   ❌ 搜索失败: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
    return True

if __name__ == "__main__":
    test_tavily_search()

