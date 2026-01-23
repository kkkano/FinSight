#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查后端初始化状态
诊断为什么报告生成器不可用
"""

import sys
import os

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("=" * 70)
print("后端初始化诊断")
print("=" * 70)

# 1. 检查 Agent 创建
print("\n1. 检查 Agent 创建...")
try:
    from backend.conversation.agent import create_agent
    
    agent = create_agent(
        use_llm=True,
        use_orchestrator=True,
        use_report_agent=True
    )
    
    print("✅ Agent 创建成功")
    print(f"   - agent.llm: {agent.llm is not None}")
    print(f"   - agent.orchestrator: {agent.orchestrator is not None}")
    print(f"   - agent.report_agent: {agent.report_agent is not None}")
    print(f"   - agent.supervisor: {agent.supervisor is not None}")
    
    # 检查 ChatHandler 状态
    print("\n2. 检查 ChatHandler 状态...")
    ch = agent.chat_handler
    print(f"   - chat_handler.llm: {ch.llm is not None}")
    print(f"   - chat_handler.orchestrator: {ch.orchestrator is not None}")
    print(f"   - chat_handler.tools_module: {ch.tools_module is not None}")
    
    # 检查 LLM 类型
    if ch.llm:
        print(f"   - LLM 类型: {type(ch.llm).__name__}")
    
    # 测试报告生成
    print("\n3. 测试报告生成...")
    result = agent.chat("分析 AAPL")
    
    print(f"   - success: {result.get('success')}")
    print(f"   - intent: {result.get('intent')}")
    print(f"   - method: {result.get('method', 'unknown')}")
    print(f"   - error: {result.get('error', 'none')}")
    
    if not result.get('success'):
        print(f"\n❌ 报告生成失败!")
        print(f"   响应: {result.get('response', '')[:300]}")
    else:
        print(f"\n✅ 报告生成成功!")
        print(f"   响应长度: {len(result.get('response', ''))}")
        print(f"   方法: {result.get('method', 'unknown')}")
    
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)

