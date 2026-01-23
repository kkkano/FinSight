#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试工具修复
验证所有工具是否能正常工作
"""

import sys
import os

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def test_tools_import():
    """测试 tools 模块导入"""
    print("=" * 70)
    print("测试 1: tools 模块导入")
    print("=" * 70)
    
    try:
        from backend import tools
        print("✅ 成功从 backend.tools 导入")
        
        # 检查关键函数
        required_funcs = ['get_stock_price', 'get_company_news', 'get_company_info']
        for func_name in required_funcs:
            if hasattr(tools, func_name):
                print(f"  ✅ {func_name} 存在")
            else:
                print(f"  ❌ {func_name} 不存在")
        
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False


def test_orchestrator():
    """测试 Orchestrator 初始化"""
    print("\n" + "=" * 70)
    print("测试 2: Orchestrator 初始化")
    print("=" * 70)
    
    try:
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        
        print("✅ Orchestrator 初始化成功")
        
        if orchestrator.tools_module:
            print("✅ tools_module 已设置")
        else:
            print("❌ tools_module 未设置")
        
        if 'price' in orchestrator.sources:
            print(f"✅ 价格数据源已注册: {len(orchestrator.sources['price'])} 个")
        else:
            print("❌ 价格数据源未注册")
        
        return True
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chat_handler():
    """测试 ChatHandler"""
    print("\n" + "=" * 70)
    print("测试 3: ChatHandler 初始化")
    print("=" * 70)
    
    try:
        from backend.handlers.chat_handler import ChatHandler
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        
        handler = ChatHandler(orchestrator=orchestrator)
        
        print("✅ ChatHandler 初始化成功")
        
        if handler.tools_module:
            print("✅ tools_module 已设置")
        else:
            print("❌ tools_module 未设置")
        
        return True
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# NOTE: test_report_handler 已移除，ReportHandler 已废弃


def test_agent_creation():
    """测试 Agent 创建"""
    print("\n" + "=" * 70)
    print("测试 4: ConversationAgent 创建")
    print("=" * 70)
    
    try:
        from backend.conversation.agent import create_agent
        
        # 测试不启用 report_agent
        agent = create_agent(
            use_llm=False,
            use_orchestrator=True,
            use_report_agent=False
        )
        
        print("✅ Agent 创建成功（无 report_agent）")
        
        if agent.orchestrator:
            print("✅ orchestrator 已设置")
        else:
            print("❌ orchestrator 未设置")
        
        if agent.chat_handler.tools_module:
            print("✅ ChatHandler.tools_module 已设置")
        else:
            print("❌ ChatHandler.tools_module 未设置")
        
        return True
    except Exception as e:
        print(f"❌ 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_langchain_agent():
    """测试 LangChain Agent 导入"""
    print("\n" + "=" * 70)
    print("测试 6: LangChain Agent 导入")
    print("=" * 70)
    
    try:
        from backend.langchain_agent import create_financial_agent
        print("✅ LangChain Agent 导入成功")
        return True
    except Exception as e:
        print(f"⚠️  LangChain Agent 导入失败: {e}")
        print("    (这可能是正常的，如果依赖未安装)")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("FinSight 工具修复验证测试")
    print("=" * 70 + "\n")
    
    results = []
    results.append(("tools 导入", test_tools_import()))
    results.append(("Orchestrator", test_orchestrator()))
    results.append(("ChatHandler", test_chat_handler()))
    # NOTE: ReportHandler 已废弃
    results.append(("Agent 创建", test_agent_creation()))
    results.append(("LangChain Agent", test_langchain_agent()))
    
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name:20s}: {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ 所有测试通过！")
    else:
        print("⚠️  部分测试失败，请检查上述错误信息")
    print("=" * 70 + "\n")

