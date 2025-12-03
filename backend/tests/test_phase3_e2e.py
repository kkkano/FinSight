# -*- coding: utf-8 -*-
"""
Phase 3 端到端测试
测试主程序和完整对话流程
"""

import sys
import os
from datetime import datetime
from io import StringIO

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def print_header(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_result(name: str, passed: bool, detail: str = ""):
    status = "✅" if passed else "❌"
    print(f"  {status} {name}")
    if detail:
        print(f"      {detail}")


def test_imports():
    """测试所有必要的导入"""
    print("\n📦 测试模块导入...")
    print("-" * 50)
    
    results = []
    
    # 测试核心模块
    modules = [
        ('backend.conversation.agent', 'ConversationAgent'),
        ('backend.conversation.context', 'ContextManager'),
        ('backend.conversation.router', 'ConversationRouter, Intent'),
        ('backend.handlers.chat_handler', 'ChatHandler'),
        ('backend.handlers.report_handler', 'ReportHandler'),
        ('backend.handlers.followup_handler', 'FollowupHandler'),
        ('backend.orchestration.orchestrator', 'ToolOrchestrator'),
        ('backend.orchestration.cache', 'DataCache'),
        ('backend.orchestration.validator', 'DataValidator'),
        ('backend.prompts.system_prompts', 'CHAT_SYSTEM_PROMPT'),
    ]
    
    for module_path, component in modules:
        try:
            module = __import__(module_path, fromlist=[component.split(',')[0].strip()])
            results.append((f"{module_path}", True, ""))
        except Exception as e:
            results.append((f"{module_path}", False, str(e)[:50]))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_main_module():
    """测试主程序模块"""
    print("\n🚀 测试主程序模块...")
    print("-" * 50)
    
    results = []
    
    try:
        # 测试 main.py 可以被导入
        import main
        results.append(("main.py 导入", True, ""))
        
        # 测试关键函数存在
        functions = [
            'print_banner',
            'print_conversation_help', 
            'run_conversation_mode',
            'run_report_mode',
            'main'
        ]
        
        for func_name in functions:
            has_func = hasattr(main, func_name)
            results.append((f"函数 {func_name}", has_func, ""))
        
        # 测试 CONVERSATION_AVAILABLE 标志
        results.append(("CONVERSATION_AVAILABLE", main.CONVERSATION_AVAILABLE, ""))
        
    except Exception as e:
        results.append(("main.py 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_conversation_flow():
    """测试完整对话流程"""
    print("\n💬 测试对话流程...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        # 创建编排器
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        results.append(("Orchestrator 初始化", True, ""))
        
        # 创建 Agent
        agent = ConversationAgent(orchestrator=orchestrator)
        results.append(("ConversationAgent 创建", True, ""))
        
        # 模拟对话流程
        conversation = [
            ("AAPL 股价多少", "chat", "获取价格"),
            ("分析一下", "report", "请求报告"),
            ("风险呢", "followup", "追问风险"),
            ("它最近有什么新闻", "chat", "查询新闻（指代解析）"),
        ]
        
        for query, expected_intent, desc in conversation:
            response = agent.chat(query)
            intent = response.get('intent', 'unknown')
            success = response.get('success', False) or 'response' in response
            
            passed = intent == expected_intent and success
            results.append((
                f"{desc}: '{query[:20]}...'", 
                passed, 
                f"意图: {intent}, 成功: {success}"
            ))
        
        # 验证上下文
        results.append((
            "上下文焦点保持", 
            agent.context.current_focus == 'AAPL',
            f"焦点: {agent.context.current_focus}"
        ))
        
        results.append((
            "对话历史记录",
            len(agent.context.history) == 4,
            f"轮数: {len(agent.context.history)}"
        ))
        
        # 验证统计
        stats = agent.get_stats()
        results.append((
            "统计信息完整",
            stats['total_queries'] == 4,
            f"总查询: {stats['total_queries']}"
        ))
        
    except Exception as e:
        import traceback
        results.append(("对话流程测试", False, str(e)))
        traceback.print_exc()
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_multi_stock_conversation():
    """测试多股票对话场景"""
    print("\n📊 测试多股票场景...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        agent = ConversationAgent(orchestrator=orchestrator)
        
        # 场景: 切换多个股票
        stocks = ['AAPL', 'TSLA', 'NVDA']
        
        for stock in stocks:
            response = agent.chat(f"{stock} 现在多少钱")
            passed = agent.context.current_focus == stock
            results.append((
                f"切换到 {stock}",
                passed,
                f"焦点: {agent.context.current_focus}"
            ))
        
        # 验证最终焦点
        results.append((
            "最终焦点正确",
            agent.context.current_focus == 'NVDA',
            ""
        ))
        
    except Exception as e:
        results.append(("多股票场景", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_error_handling():
    """测试错误处理"""
    print("\n⚠️ 测试错误处理...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        
        agent = ConversationAgent()
        
        # 测试模糊查询
        response = agent.chat("它怎么样")
        # 应该请求澄清或返回合理响应
        has_response = 'response' in response
        results.append((
            "模糊查询处理",
            has_response,
            f"响应长度: {len(response.get('response', ''))}"
        ))
        
        # 测试空查询
        response = agent.chat("")
        # 应该不崩溃
        results.append(("空查询处理", True, "未崩溃"))
        
        # 测试无效股票代码
        response = agent.chat("XXXXX123 股价")
        has_response = 'response' in response
        results.append((
            "无效代码处理",
            has_response,
            ""
        ))
        
    except Exception as e:
        results.append(("错误处理测试", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_chinese_input():
    """测试中文输入"""
    print("\n🇨🇳 测试中文输入...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        orchestrator = ToolOrchestrator()
        register_all_financial_tools(orchestrator)
        agent = ConversationAgent(orchestrator=orchestrator)
        
        # 测试中文公司名
        test_cases = [
            ("苹果公司股价", 'AAPL', "苹果→AAPL"),
            ("特斯拉怎么样", 'TSLA', "特斯拉→TSLA"),
            ("分析英伟达", 'NVDA', "英伟达→NVDA"),
        ]
        
        for query, expected_ticker, desc in test_cases:
            response = agent.chat(query)
            focus = agent.context.current_focus
            passed = focus == expected_ticker
            results.append((desc, passed, f"识别: {focus}"))
        
    except Exception as e:
        results.append(("中文输入测试", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_session_management():
    """测试会话管理"""
    print("\n🔄 测试会话管理...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        
        agent = ConversationAgent()
        
        # 进行一些对话
        agent.chat("AAPL 股价")
        agent.chat("详细说说")
        
        initial_turns = len(agent.context.history)
        results.append(("对话记录", initial_turns == 2, f"轮数: {initial_turns}"))
        
        # 测试重置
        agent.reset()
        results.append((
            "重置后历史清空",
            len(agent.context.history) == 0,
            ""
        ))
        
        results.append((
            "重置后焦点清空",
            agent.context.current_focus is None,
            ""
        ))
        
        results.append((
            "重置后统计清零",
            agent.stats['total_queries'] == 0,
            ""
        ))
        
        # 重置后可以继续使用
        response = agent.chat("MSFT 股价")
        results.append((
            "重置后可继续使用",
            'response' in response,
            ""
        ))
        
    except Exception as e:
        results.append(("会话管理测试", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def main():
    """运行所有测试"""
    print_header("Phase 3 端到端测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # 运行测试
    results['模块导入'] = test_imports()
    results['主程序模块'] = test_main_module()
    results['对话流程'] = test_conversation_flow()
    results['多股票场景'] = test_multi_stock_conversation()
    results['错误处理'] = test_error_handling()
    results['中文输入'] = test_chinese_input()
    results['会话管理'] = test_session_management()
    
    # 汇总结果
    print_header("Phase 3 测试结果汇总")
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    passed_count = sum(1 for p in results.values() if p)
    total_count = len(results)
    
    print(f"\n总计: {passed_count}/{total_count} 测试通过")
    
    if all_passed:
        print("\n🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
        print("🎉 Phase 3 端到端测试全部通过！")
        print("🎉 对话式 Agent 已可使用")
        print("🎉 运行 python main.py 开始体验")
        print("🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
    else:
        print("\n⚠️ 部分测试未通过，请检查上述失败项")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

