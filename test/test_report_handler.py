#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 ReportHandler 修复
验证报告生成器是否能正常工作
"""

import sys
import os

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def test_report_handler_without_llm():
    """测试没有 LLM 时的报告生成"""
    print("=" * 70)
    print("测试 1: ReportHandler（无 LLM，无 Agent）")
    print("=" * 70)
    
    try:
        from backend.handlers.report_handler import ReportHandler
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        
        handler = ReportHandler(
            agent=None,
            orchestrator=orchestrator,
            llm=None
        )
        
        print("✅ ReportHandler 初始化成功")
        print(f"  - orchestrator: {handler.orchestrator is not None}")
        print(f"  - tools_module: {handler.tools_module is not None}")
        print(f"  - llm: {handler.llm is not None}")
        print(f"  - agent: {handler.agent is not None}")
        
        # 测试处理（不实际调用 API，只测试逻辑）
        result = handler.handle(
            query="分析 AAPL",
            metadata={'tickers': ['AAPL']},
            context=None
        )
        
        print(f"\n处理结果:")
        print(f"  - success: {result.get('success')}")
        print(f"  - method: {result.get('method', 'unknown')}")
        print(f"  - response length: {len(result.get('response', ''))}")
        
        if result.get('success'):
            print("✅ 报告生成成功（使用基础数据收集）")
            return True
        else:
            print(f"❌ 报告生成失败: {result.get('error', 'unknown')}")
            print(f"   响应: {result.get('response', '')[:200]}")
            return False
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_report_handler_with_orchestrator():
    """测试有 orchestrator 时的报告生成"""
    print("\n" + "=" * 70)
    print("测试 2: ReportHandler（有 orchestrator，无 LLM）")
    print("=" * 70)
    
    try:
        from backend.conversation.agent import create_agent
        
        agent = create_agent(
            use_llm=False,  # 不使用 LLM
            use_orchestrator=True,
            use_report_agent=False
        )
        
        print("✅ Agent 创建成功")
        print(f"  - report_handler.orchestrator: {agent.report_handler.orchestrator is not None}")
        print(f"  - report_handler.tools_module: {agent.report_handler.tools_module is not None}")
        print(f"  - report_handler.llm: {agent.report_handler.llm is not None}")
        
        # 测试报告生成
        result = agent.chat("分析 AAPL")
        
        print(f"\n处理结果:")
        print(f"  - success: {result.get('success')}")
        print(f"  - intent: {result.get('intent')}")
        print(f"  - response length: {len(result.get('response', ''))}")
        
        if result.get('success') and result.get('intent') == 'report':
            print("✅ 报告生成成功")
            return True
        else:
            print(f"⚠️  结果: {result.get('response', '')[:200]}")
            return False
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("ReportHandler 修复验证测试")
    print("=" * 70 + "\n")
    
    results = []
    results.append(("无 LLM 报告生成", test_report_handler_without_llm()))
    results.append(("Agent 报告生成", test_report_handler_with_orchestrator()))
    
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name:30s}: {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ 所有测试通过！报告生成器应该能正常工作了。")
    else:
        print("⚠️  部分测试失败，请检查上述错误信息")
    print("=" * 70 + "\n")

