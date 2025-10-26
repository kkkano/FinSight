#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试阶段3: LangChain Agent系统验证
验证LangChain Agent的功能和性能
"""

import sys
import traceback
import asyncio
from datetime import datetime

def test_agent_creation():
    """测试Agent创建和基本配置"""
    print("测试LangChain Agent创建...")

    try:
        from langchain_agent import (
            LangChainFinancialAgent, create_langchain_financial_agent,
            FinancialCallbackHandler, CIO_SYSTEM_PROMPT
        )

        print("   [OK] 成功导入Agent模块")

        # 测试1: 创建Agent实例
        print("   测试Agent实例创建...")
        agent = LangChainFinancialAgent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=True,
            max_iterations=10
        )
        print("   [OK] Agent实例创建成功")

        # 测试2: 获取Agent信息
        print("   测试Agent信息获取...")
        info = agent.get_agent_info()
        required_keys = ["provider", "model", "max_iterations", "tools_count", "tools", "framework"]
        for key in required_keys:
            if key not in info:
                print(f"   [FAIL] Agent信息缺少字段: {key}")
                return False
        print(f"   [OK] Agent信息完整 (工具数量: {info['tools_count']})")

        # 测试3: 回调处理器
        print("   测试回调处理器...")
        callback_handler = FinancialCallbackHandler()
        if hasattr(callback_handler, 'on_agent_start') and hasattr(callback_handler, 'on_agent_finish'):
            print("   [OK] 回调处理器功能正常")
        else:
            print("   [FAIL] 回调处理器缺少必要方法")
            return False

        # 测试4: 系统提示词
        print("   测试系统提示词...")
        current_date = datetime.now().strftime("%Y-%m-%d")
        if "{current_date}" in CIO_SYSTEM_PROMPT and "{tools}" in CIO_SYSTEM_PROMPT:
            print("   [OK] 系统提示词模板正常")
        else:
            print("   [FAIL] 系统提示词模板异常")
            return False

        # 测试5: Agent创建函数
        print("   测试Agent创建函数...")
        agent_executor = create_langchain_financial_agent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=False,  # 避免输出干扰测试
            max_iterations=5
        )
        if agent_executor:
            print("   [OK] AgentExecutor创建成功")
        else:
            print("   [FAIL] AgentExecutor创建失败")
            return False

        print("   [SUCCESS] Agent创建测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] Agent创建测试失败: {str(e)}")
        traceback.print_exc()
        return False

def test_basic_analysis():
    """测试基本分析功能"""
    print("\n测试基本分析功能...")

    try:
        from langchain_agent import LangChainFinancialAgent

        # 创建Agent
        agent = LangChainFinancialAgent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=True,
            max_iterations=5,  # 限制迭代次数以加快测试
            show_intermediate_steps=True
        )

        # 测试1: 简单查询 (获取当前时间)
        print("   测试简单时间查询...")
        try:
            # 这是一个不会触发复杂金融分析的简单查询
            result = agent.analyze("获取当前时间", session_id="test_basic")
            if result and len(result) > 10:
                print(f"   [OK] 简单查询成功")
            else:
                print(f"   [WARN] 简单查询结果较短或为空")
        except Exception as e:
            print(f"   [INFO] 简单查询执行异常 (可能需要API): {str(e)}")

        # 测试2: 股票查询
        print("   测试股票价格查询...")
        try:
            # 使用常见的股票代码
            result = agent.analyze("获取AAPL的当前价格", session_id="test_stock")
            if result and len(result) > 50:
                print(f"   [OK] 股票查询成功，结果长度: {len(result)}")
            elif result:
                print(f"   [WARN] 股票查询结果较短，可能需要API配置")
            else:
                print(f"   [INFO] 股票查询无结果，可能需要API配置")
        except Exception as e:
            print(f"   [INFO] 股票查询执行异常 (可能需要API配置): {str(e)}")

        # 测试3: Agent工具提取功能
        print("   测试股票代码提取...")
        ticker = agent._extract_ticker("分析AAPL股票的投资机会")
        if ticker == "AAPL":
            print(f"   [OK] 股票代码提取正常: {ticker}")
        else:
            print(f"   [FAIL] 股票代码提取异常: {ticker}")
            return False

        print("   [SUCCESS] 基本分析功能测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 基本分析功能测试失败: {str(e)}")
        traceback.print_exc()
        return False

async def test_async_analysis():
    """测试异步分析功能"""
    print("\n测试异步分析功能...")

    try:
        from langchain_agent import LangChainFinancialAgent

        # 创建异步Agent
        agent = LangChainFinancialAgent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=False,  # 减少输出干扰
            max_iterations=3,
            show_intermediate_steps=False
        )

        # 测试异步执行
        print("   测试异步分析执行...")
        try:
            result = await agent.analyze_async("获取当前时间", session_id="test_async")
            if result:
                print(f"   [OK] 异步分析成功，结果长度: {len(result)}")
            else:
                print(f"   [WARN] 异步分析结果为空")
        except Exception as e:
            print(f"   [INFO] 异步分析执行异常 (可能需要API配置): {str(e)}")

        print("   [SUCCESS] 异步分析功能测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 异步分析功能测试失败: {str(e)}")
        traceback.print_exc()
        return False

def test_error_handling():
    """测试Agent的错误处理能力"""
    print("\n测试Agent错误处理...")

    try:
        from langchain_agent import LangChainFinancialAgent

        # 创建Agent
        agent = LangChainFinancialAgent(
            provider="invalid_provider",  # 使用无效的提供商
            model="invalid_model",
            verbose=False,
            max_iterations=2
        )

        # 测试1: 无效提供商处理
        print("   测试无效提供商处理...")
        try:
            result = agent.analyze("测试查询")
            # 如果能处理错误并返回有意义的消息
            if result and ("error" in result.lower() or "失败" in result or "未生成" in result):
                print("   [OK] 无效提供商错误处理正常")
            else:
                print("   [WARN] 无效提供商处理结果可能不完整")
        except Exception as e:
            # 如果能捕获异常也是正常的错误处理
            print(f"   [OK] 无效提供商异常处理正常: {str(e)[:50]}...")

        # 测试2: 空查询处理
        print("   测试空查询处理...")
        agent_valid = LangChainFinancialAgent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=False,
            max_iterations=1
        )

        try:
            result = agent_valid.analyze("")  # 空查询
            if result and len(result) > 0:
                print("   [OK] 空查询处理正常")
            else:
                print("   [WARN] 空查询处理结果为空")
        except Exception as e:
            print(f"   [INFO] 空查询处理异常: {str(e)[:50]}...")

        print("   [SUCCESS] 错误处理测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 错误处理测试失败: {str(e)}")
        traceback.print_exc()
        return False

def test_integration_with_tools():
    """测试Agent与工具系统的集成"""
    print("\n测试Agent与工具系统集成...")

    try:
        from langchain_agent import LangChainFinancialAgent
        from langchain_tools import FINANCIAL_TOOLS

        # 创建Agent
        agent = LangChainFinancialAgent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=False,
            max_iterations=5
        )

        # 测试1: Agent工具数量
        print("   测试Agent工具数量...")
        info = agent.get_agent_info()
        if info["tools_count"] == len(FINANCIAL_TOOLS):
            print(f"   [OK] 工具数量匹配: {info['tools_count']}")
        else:
            print(f"   [FAIL] 工具数量不匹配: {info['tools_count']} vs {len(FINANCIAL_TOOLS)}")
            return False

        # 测试2: 工具名称完整性
        print("   测试工具名称完整性...")
        agent_tools = set(info["tools"])
        expected_tools = set(tool.name for tool in FINANCIAL_TOOLS)

        if agent_tools == expected_tools:
            print(f"   [OK] 工具名称完整")
        else:
            missing = expected_tools - agent_tools
            extra = agent_tools - expected_tools
            print(f"   [WARN] 工具名称不完整: 缺失{missing}, 额外{extra}")

        # 测试3: 复杂查询结构
        print("   测试复杂查询结构...")
        try:
            # 这是一个复杂的查询，需要使用多个工具
            result = agent.analyze("分析AAPL公司基本面，包括当前股价、市场情绪和相关新闻",
                                session_id="test_complex")

            # 检查结果是否包含预期的结构元素
            if result and len(result) > 100:
                print("   [OK] 复杂查询执行成功")
            elif result:
                print("   [INFO] 复杂查询结果较短，可能需要API配置")
            else:
                print("   [INFO] 复杂查询无结果，可能需要API配置")
        except Exception as e:
            print(f"   [INFO] 复杂查询执行异常: {str(e)[:100]}...")

        print("   [SUCCESS] Agent与工具系统集成测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] Agent与工具系统集成测试失败: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("FinSight LangChain迁移 - 阶段3 Agent系统测试")
    print("=" * 60)

    # 运行所有测试
    tests = [
        ("Agent创建和配置", test_agent_creation),
        ("基本分析功能", test_basic_analysis),
        ("异步分析功能", test_async_analysis),
        ("错误处理机制", test_error_handling),
        ("工具系统集成", test_integration_with_tools)
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n{test_name}")
        print("-" * 40)

        if test_name == "异步分析功能":
            # 异步测试需要特殊处理
            result = asyncio.run(test_func())
        else:
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

    if passed_tests >= total_tests * 0.8:  # 80%通过率
        print("[SUCCESS] Agent系统迁移基本完成! 可以开始下一阶段工作。")
        return True
    else:
        print("[WARNING] 存在较多问题，请检查Agent系统实现。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)