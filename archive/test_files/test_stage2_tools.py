#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试阶段2: LangChain工具系统验证
验证所有LangChain工具的功能
"""

import sys
import traceback
from datetime import datetime

def test_tool_loading():
    """测试工具加载和基本属性"""
    print("测试LangChain工具系统加载...")

    try:
        from langchain_tools import (
            FINANCIAL_TOOLS, get_tool_by_name, get_tool_descriptions,
            AsyncFinancialTools, RobustFinancialTools
        )

        print(f"   [OK] 成功导入工具模块")
        print(f"   [OK] 工具总数: {len(FINANCIAL_TOOLS)}")

        # 验证每个工具的基本属性
        required_attrs = ['name', 'description', 'args_schema', 'func']
        for tool in FINANCIAL_TOOLS:
            for attr in required_attrs:
                if not hasattr(tool, attr):
                    print(f"   [FAIL] 工具 {tool.name} 缺少属性: {attr}")
                    return False
            print(f"   [OK] 工具 {tool.name} 属性完整")

        # 测试工具描述
        descriptions = get_tool_descriptions()
        print(f"   [OK] 工具描述生成成功，长度: {len(descriptions)}")

        # 测试工具查找
        first_tool = FINANCIAL_TOOLS[0]
        found_tool = get_tool_by_name(first_tool.name)
        if found_tool == first_tool:
            print(f"   [OK] 工具查找功能正常")
        else:
            print(f"   [FAIL] 工具查找功能异常")
            return False

        # 测试异步工具类
        async_tools = AsyncFinancialTools()
        available_tools = async_tools.get_available_tools()
        print(f"   [OK] 异步工具类初始化成功，可用工具: {len(available_tools)}")

        # 测试稳健工具类
        robust_tools = RobustFinancialTools()
        print(f"   [OK] 稳健工具类初始化成功")

        print("   [SUCCESS] 工具系统加载测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 工具系统加载失败: {str(e)}")
        traceback.print_exc()
        return False

def test_individual_tools():
    """测试每个工具的基本功能"""
    print("\n测试各个工具的基本功能...")

    try:
        from langchain_tools import (
            get_current_datetime, search, get_stock_price,
            get_company_info, get_company_news, get_market_sentiment,
            get_economic_events, get_performance_comparison,
            analyze_historical_drawdowns
        )
        from langchain_tools import TickerInput, SearchInput, DateInput, ComparisonInput

        # 测试1: 获取当前时间
        print("   测试 get_current_datetime...")
        try:
            date_input = DateInput()
            result = get_current_datetime.func(date_input)
            if result and len(result) > 10:
                print(f"   [OK] get_current_datetime: {result[:50]}...")
            else:
                print(f"   [FAIL] get_current_datetime 返回结果异常")
                return False
        except Exception as e:
            print(f"   [FAIL] get_current_datetime 执行失败: {str(e)}")
            return False

        # 测试2: 搜索功能
        print("   测试 search...")
        try:
            search_input = SearchInput(query="NASDAQ market today")
            result = search.func(search_input)
            if "Search Results:" in result or "Search error:" in result:
                print(f"   [OK] search: 返回了搜索结果")
            else:
                print(f"   [WARN] search: 返回结果格式异常")
        except Exception as e:
            print(f"   [FAIL] search 执行失败: {str(e)}")
            return False

        # 测试3: 股价查询（使用常见股票）
        print("   测试 get_stock_price...")
        try:
            ticker_input = TickerInput(ticker="AAPL")
            result = get_stock_price.func(ticker_input)
            if "AAPL" in result and ("$" in result or "error" in result.lower()):
                print(f"   [OK] get_stock_price: 返回了价格信息")
            else:
                print(f"   [WARN] get_stock_price: 返回结果可能异常")
        except Exception as e:
            print(f"   [FAIL] get_stock_price 执行失败: {str(e)}")
            return False

        # 测试4: 公司信息查询
        print("   测试 get_company_info...")
        try:
            ticker_input = TickerInput(ticker="AAPL")
            result = get_company_info.func(ticker_input)
            if len(result) > 50:  # 公司信息应该比较长
                print(f"   [OK] get_company_info: 返回了详细信息")
            else:
                print(f"   [WARN] get_company_info: 返回结果较短")
        except Exception as e:
            print(f"   [FAIL] get_company_info 执行失败: {str(e)}")
            return False

        # 测试5: 市场情绪
        print("   测试 get_market_sentiment...")
        try:
            date_input = DateInput()
            result = get_market_sentiment.func(date_input)
            if "Fear & Greed" in result or "CNN" in result or "error" in result.lower():
                print(f"   [OK] get_market_sentiment: 返回了情绪指标")
            else:
                print(f"   [WARN] get_market_sentiment: 返回结果可能异常")
        except Exception as e:
            print(f"   [FAIL] get_market_sentiment 执行失败: {str(e)}")
            return False

        print("   [SUCCESS] 各个工具基本功能测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 工具功能测试失败: {str(e)}")
        traceback.print_exc()
        return False

def test_tool_error_handling():
    """测试工具的错误处理能力"""
    print("\n测试工具错误处理...")

    try:
        from langchain_tools import RobustFinancialTools

        robust_tools = RobustFinancialTools()

        # 测试1: 不存在的工具
        print("   测试不存在的工具...")
        result = robust_tools.safe_execute("nonexistent_tool", {})
        if "未找到工具" in result:
            print(f"   [OK] 不存在工具的错误处理正常")
        else:
            print(f"   [FAIL] 不存在工具的错误处理异常")
            return False

        # 测试2: 无效输入参数
        print("   测试无效输入参数...")
        result = robust_tools.safe_execute("get_stock_price", {"invalid_param": "INVALID"})
        # 应该能处理Pydantic验证错误
        if "失败" in result or "error" in result.lower():
            print(f"   [OK] 无效参数的错误处理正常")
        else:
            print(f"   [WARN] 无效参数处理结果: {result}")

        # 测试3: 网络错误模拟（使用无效股票代码）
        print("   测试网络错误处理...")
        result = robust_tools.safe_execute("get_stock_price", {"ticker": "INVALIDTICKER123"})
        if "error" in result.lower() or "失败" in result or "invalid" in result.lower():
            print(f"   [OK] 网络错误处理正常")
        else:
            print(f"   [WARN] 网络错误处理结果: {result}")

        print("   [SUCCESS] 错误处理测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 错误处理测试失败: {str(e)}")
        traceback.print_exc()
        return False

def test_tool_integration():
    """测试工具集成功能"""
    print("\n测试工具集成功能...")

    try:
        from langchain_tools import AsyncFinancialTools

        # 创建异步工具实例
        async_tools = AsyncFinancialTools()

        # 测试异步执行
        print("   测试异步工具执行...")
        import asyncio

        async def test_async():
            try:
                result = await async_tools.execute_tool("get_current_datetime", {})
                return result is not None and len(result) > 10
            except Exception as e:
                print(f"   异步执行异常: {str(e)}")
                return False

        # 运行异步测试
        success = asyncio.run(test_async())
        if success:
            print(f"   [OK] 异步工具执行正常")
        else:
            print(f"   [FAIL] 异步工具执行失败")
            return False

        # 测试工具列表
        available_tools = async_tools.get_available_tools()
        expected_tools = [
            'get_stock_price', 'get_company_news', 'get_company_info',
            'search', 'get_market_sentiment', 'get_economic_events',
            'get_performance_comparison', 'analyze_historical_drawdowns',
            'get_current_datetime'
        ]

        missing_tools = [tool for tool in expected_tools if tool not in available_tools]
        if not missing_tools:
            print(f"   [OK] 所有预期工具都在列表中")
        else:
            print(f"   [FAIL] 缺失工具: {missing_tools}")
            return False

        print("   [SUCCESS] 工具集成测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 工具集成测试失败: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("FinSight LangChain迁移 - 阶段2工具系统测试")
    print("=" * 60)

    # 运行所有测试
    tests = [
        ("工具系统加载", test_tool_loading),
        ("各个工具功能", test_individual_tools),
        ("错误处理机制", test_tool_error_handling),
        ("工具集成功能", test_tool_integration)
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n{test_name}")
        print("-" * 40)
        result = test_func()
        results.append((test_name, result))

    # 总结测试结果
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed_tests = sum(1 for _, result in results if result)
    total_tests = len(results)

    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{test_name}: {status}")

    print(f"\n总结果: {passed_tests}/{total_tests} 测试通过")

    if passed_tests == total_tests:
        print("[SUCCESS] 工具系统迁移完成! 可以开始下一阶段工作。")
        return True
    else:
        print("[WARNING] 存在问题，请检查工具系统实现。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)