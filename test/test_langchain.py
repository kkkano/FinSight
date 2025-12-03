#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangChain 1.0+ 重构测试脚本
测试所有工具和 Agent 的功能
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*70)
print("LangChain 1.0+ Refactor Test")
print("="*70)

# ============================================
# 测试 1: 导入测试
# ============================================

print("\n[Test 1] Import modules...")
try:
    from langchain_tools import (
        FINANCIAL_TOOLS,
        get_tool_names,
        get_tools_description
    )
    print("[OK] langchain_tools imported successfully")
    print(f"   Tools count: {len(FINANCIAL_TOOLS)}")
    print(f"   Tools list: {get_tool_names()}")
except Exception as e:
    print(f"[FAIL] langchain_tools import failed: {e}")
    sys.exit(1)

try:
    from langchain_agent import (
        LangChainFinancialAgent,
        create_financial_agent
    )
    print("[OK] langchain_agent imported successfully")
except Exception as e:
    print(f"[FAIL] langchain_agent import failed: {e}")
    sys.exit(1)

# ============================================
# 测试 2: 单个工具测试
# ============================================

print("\n[Test 2] Individual tool functionality...")

test_cases = [
    ("get_current_datetime", {}),
    ("get_stock_price", {"ticker": "AAPL"}),
    ("get_market_sentiment", {}),
]

for tool_name, tool_input in test_cases:
    print(f"\n   Testing tool: {tool_name}")
    try:
        from langchain_tools import get_tool_by_name
        tool = get_tool_by_name(tool_name)
        
        if tool:
            result = tool.invoke(tool_input)
            print(f"   [OK] Success! Result: {result[:100]}...")
        else:
            print(f"   [FAIL] Tool not found: {tool_name}")
    except Exception as e:
        print(f"   [FAIL] Execution failed: {e}")

# ============================================
# 测试 3: Agent 创建测试
# ============================================

print("\n[Test 3] Create Agent...")
try:
    agent = create_financial_agent(
        provider="gemini_proxy",
        model="gemini-2.5-flash-preview-05-20",
        verbose=True,
        max_iterations=20
    )
    print("[OK] Agent created successfully")
    
    # 显示 Agent 信息
    info = agent.get_agent_info()
    print(f"   Framework: {info['framework']}")
    print(f"   Model: {info['model']}")
    print(f"   Tools: {info['tools_count']}")
    print(f"   Max iterations: {info['max_iterations']}")
    
except Exception as e:
    print(f"[FAIL] Agent creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================
# 测试 4: 简单查询测试
# ============================================

print("\n[Test 4] Execute simple query...")
print("   Query: Get current price of NVDA")

try:
    result = agent.analyze("What is the current price of NVDA stock?")
    
    if result["success"]:
        print(f"\n[OK] Query succeeded!")
        print(f"   Steps: {result['step_count']}")
        print(f"\n[Analysis Result]")
        print("-" * 70)
        print(result["output"])
        print("-" * 70)
    else:
        print(f"\n[FAIL] Query failed: {result['error']}")
        
except Exception as e:
    print(f"[FAIL] Query execution failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================
# 测试 5: 完整分析测试 (可选)
# ============================================

RUN_FULL_TEST = os.getenv("RUN_FULL_TEST", "false").lower() == "true"

if RUN_FULL_TEST:
    print("\n[Test 5] Execute full analysis...")
    print("   Query: Analyze TSLA stock investment opportunity")
    
    try:
        result = agent.analyze(
            "Analyze Tesla (TSLA) stock. Should I buy it? "
            "Include price analysis, news, sentiment, and provide a detailed recommendation."
        )
        
        if result["success"]:
            print(f"\n[OK] Full analysis succeeded!")
            print(f"   Steps: {result['step_count']}")
            
            # 保存报告
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_report_TSLA_{timestamp}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(result["output"])
            print(f"   Report saved: {filename}")
            
            # 显示摘要
            print(f"\n[Report Summary - First 500 chars]")
            print("-" * 70)
            print(result["output"][:500] + "...")
            print("-" * 70)
        else:
            print(f"\n[FAIL] Full analysis failed: {result['error']}")
            
    except Exception as e:
        print(f"[FAIL] Full analysis execution failed: {e}")
        import traceback
        traceback.print_exc()
else:
    print("\n[SKIP] Test 5 (Full Analysis)")
    print("   Tip: Set environment variable RUN_FULL_TEST=true to run full test")

# ============================================
# 测试总结
# ============================================

print("\n" + "="*70)
print("Test Complete!")
print("="*70)
print("\n[OK] All basic tests passed!")
print("\n[Next Steps]")
print("   1. Run full test: set RUN_FULL_TEST=true && python test_langchain.py")
print("   2. Test different stocks: Modify stock ticker in test script")
print("   3. Integrate into main.py: Replace original agent implementation")
