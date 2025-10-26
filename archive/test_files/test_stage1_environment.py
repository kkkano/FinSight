#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试阶段1: 验证LangChain依赖安装
"""

import sys
import importlib

def test_langchain_imports():
    """测试所有LangChain相关包的导入"""
    print("测试LangChain依赖包导入...")

    # 测试包列表 (移除不存在的包)
    packages = [
        'langchain',
        'langchain_core',
        'langchain_openai',
        'langchain_anthropic',
        'langchain_community',
        'langgraph',
        'tenacity',
        'pydantic'
    ]

    success_count = 0
    failed_packages = []

    for package in packages:
        try:
            module = importlib.import_module(package)
            version = getattr(module, '__version__', 'Unknown')
            print(f"   [OK] {package}: {version}")
            success_count += 1
        except ImportError as e:
            print(f"   [FAIL] {package}: 导入失败 - {str(e)}")
            failed_packages.append(package)

    print(f"\n导入测试结果:")
    print(f"   成功: {success_count}/{len(packages)}")

    if failed_packages:
        print(f"   失败的包: {', '.join(failed_packages)}")
        return False
    else:
        print("   [SUCCESS] 所有依赖包导入成功!")
        return True

def test_core_langchain_functionality():
    """测试核心LangChain功能"""
    print("\n测试核心LangChain功能...")

    try:
        from langchain_core.tools import tool
        from pydantic import BaseModel, Field  # 使用pydantic而不是pydantic_v1
        from langchain_core.prompts import ChatPromptTemplate
        from langgraph.graph import StateGraph
        from pydantic import ValidationError

        # 测试工具装饰器
        class TestInput(BaseModel):
            message: str = Field(description="测试消息")

        @tool(args_schema=TestInput)
        def test_tool(input_data: TestInput) -> str:
            """测试工具"""
            return f"收到消息: {input_data.message}"

        print("   [OK] @tool装饰器工作正常")

        # 测试Prompt模板
        prompt = ChatPromptTemplate.from_template("测试: {input}")
        print("   [OK] ChatPromptTemplate工作正常")

        # 测试StateGraph
        from typing import TypedDict
        class TestState(TypedDict):
            messages: list

        workflow = StateGraph(TestState)
        print("   [OK] StateGraph工作正常")

        print("   [SUCCESS] 核心功能测试通过!")
        return True

    except Exception as e:
        print(f"   [FAIL] 核心功能测试失败: {str(e)}")
        return False

def test_existing_dependencies():
    """测试现有依赖包"""
    print("\n测试现有依赖包...")

    existing_packages = [
        ('litellm', 'LiteLLM'),
        ('ddgs', 'DuckDuckGo Search'),
        ('yfinance', 'Yahoo Finance'),
        ('requests', 'HTTP Requests'),
        ('pandas', 'Data Processing'),
        ('dotenv', 'Environment Variables')
    ]

    success_count = 0

    for package_name, display_name in existing_packages:
        try:
            if package_name == 'dotenv':
                importlib.import_module('dotenv')
            else:
                importlib.import_module(package_name)
            print(f"   [OK] {display_name}")
            success_count += 1
        except ImportError as e:
            print(f"   [FAIL] {display_name}: {str(e)}")

    print(f"\n现有依赖测试结果: {success_count}/{len(existing_packages)}")
    return success_count == len(existing_packages)

def main():
    """主测试函数"""
    print("FinSight LangChain迁移 - 阶段1环境测试")
    print("=" * 60)

    # 运行所有测试
    tests = [
        ("LangChain依赖导入", test_langchain_imports),
        ("核心LangChain功能", test_core_langchain_functionality),
        ("现有依赖包", test_existing_dependencies)
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
        print("[SUCCESS] 环境准备完成! 可以开始下一阶段迁移工作。")
        return True
    else:
        print("[WARNING] 存在问题，请先解决依赖安装问题再继续。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)