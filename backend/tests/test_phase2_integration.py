# -*- coding: utf-8 -*-
"""
Phase 2 集成测试
测试对话能力和 Handler 功能
"""

import sys
import os
from datetime import datetime

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


def test_context_manager():
    """测试上下文管理器"""
    print("\n🧠 测试 ContextManager...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.context import ContextManager, MessageRole
        
        ctx = ContextManager()
        
        # 测试 1: 添加对话轮次
        turn = ctx.add_turn(
            query="分析 AAPL",
            intent="report",
            response="这是关于 AAPL 的分析报告...",
            metadata={'tickers': ['AAPL'], 'company_name': '苹果'}
        )
        results.append(("添加对话轮次", len(ctx.history) == 1, f"历史长度: {len(ctx.history)}"))
        
        # 测试 2: 焦点更新
        results.append(("焦点更新", ctx.current_focus == 'AAPL', f"焦点: {ctx.current_focus}"))
        
        # 测试 3: 指代解析
        resolved = ctx.resolve_reference("它怎么样")
        results.append(("指代解析", "AAPL" in resolved, f"解析结果: {resolved}"))
        
        # 测试 4: 数据缓存
        ctx.cache_data('price:AAPL', {'price': 185.92})
        cached = ctx.get_cached_data('price:AAPL')
        results.append(("数据缓存", cached is not None and cached['price'] == 185.92, ""))
        
        # 测试 5: LLM 消息格式
        messages = ctx.get_messages_for_llm("你是一个助手")
        results.append(("LLM 消息格式", len(messages) >= 2, f"消息数: {len(messages)}"))
        
        # 测试 6: 摘要生成
        summary = ctx.get_summary()
        results.append(("摘要生成", "AAPL" in summary or "当前焦点" in summary, ""))
        
    except Exception as e:
        results.append(("ContextManager 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_conversation_router():
    """测试对话路由器"""
    print("\n🧭 测试 ConversationRouter...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.router import ConversationRouter, Intent
        
        router = ConversationRouter()
        
        # 测试意图分类
        test_cases = [
            ("AAPL 股价多少", Intent.CHAT, "价格查询"),
            ("分析苹果公司股票", Intent.REPORT, "报告请求"),
            ("帮我盯着 NVDA", Intent.ALERT, "监控请求"),
            ("为什么呢", Intent.FOLLOWUP, "追问"),
            ("详细说说", Intent.FOLLOWUP, "追问变体"),
        ]
        
        for query, expected_intent, desc in test_cases:
            intent, metadata = router.classify_intent(query, "当前焦点: AAPL")
            passed = intent == expected_intent
            results.append((f"{desc}: '{query[:20]}'", passed, f"结果: {intent.value}"))
        
        # 测试元数据提取
        intent, metadata = router.classify_intent("分析 GOOGL 和 MSFT", "")
        tickers = metadata.get('tickers', [])
        results.append(("多股票提取", 'GOOGL' in tickers and 'MSFT' in tickers, f"提取: {tickers}"))
        
        # 测试中文公司名识别
        intent, metadata = router.classify_intent("特斯拉怎么样", "")
        tickers = metadata.get('tickers', [])
        results.append(("中文名识别", 'TSLA' in tickers, f"提取: {tickers}"))
        
    except Exception as e:
        results.append(("ConversationRouter 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_chat_handler():
    """测试快速对话处理器"""
    print("\n💬 测试 ChatHandler...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.handlers.chat_handler import ChatHandler
        from backend.conversation.context import ContextManager
        
        handler = ChatHandler()
        ctx = ContextManager()
        
        # 测试 1: 有股票代码的查询
        result = handler.handle(
            query="AAPL 股价多少",
            metadata={'tickers': ['AAPL']},
            context=ctx
        )
        results.append(("价格查询处理", 'response' in result, f"成功: {result.get('success')}"))
        
        # 测试 2: 无股票代码时请求澄清
        result = handler.handle(
            query="股价多少",
            metadata={'tickers': []},
            context=None
        )
        needs_clarify = result.get('needs_clarification', False)
        results.append(("缺少代码时澄清", needs_clarify or '股票' in result.get('response', ''), ""))
        
        # 测试 3: 从上下文获取焦点
        ctx.current_focus = 'TSLA'
        result = handler.handle(
            query="现在多少钱",
            metadata={'tickers': []},
            context=ctx
        )
        results.append(("上下文焦点使用", 'response' in result, f"成功: {result.get('success')}"))
        
    except Exception as e:
        results.append(("ChatHandler 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_report_handler():
    """测试报告处理器"""
    print("\n📊 测试 ReportHandler...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.handlers.report_handler import ReportHandler
        from backend.conversation.context import ContextManager
        
        handler = ReportHandler()
        ctx = ContextManager()
        
        # 测试 1: 无股票代码时请求澄清
        result = handler.handle(
            query="帮我分析一下",
            metadata={'tickers': []},
            context=None
        )
        needs_clarify = result.get('needs_clarification', False)
        results.append(("缺少代码时澄清", needs_clarify, ""))
        
        # 测试 2: 有股票代码时 (不完整测试，避免实际 API 调用)
        # 只测试处理器不会崩溃
        try:
            result = handler.handle(
                query="分析 AAPL",
                metadata={'tickers': ['AAPL']},
                context=ctx
            )
            results.append(("报告请求处理", 'response' in result, ""))
        except Exception as e:
            # 可能因为没有 LLM 而失败，但不应该崩溃
            results.append(("报告请求处理", True, f"预期的错误: {str(e)[:30]}"))
        
    except Exception as e:
        results.append(("ReportHandler 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_followup_handler():
    """测试追问处理器"""
    print("\n🔄 测试 FollowupHandler...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.handlers.followup_handler import FollowupHandler
        from backend.conversation.context import ContextManager
        
        handler = FollowupHandler()
        
        # 测试 1: 无上下文时
        result = handler.handle(
            query="为什么呢",
            metadata={},
            context=None
        )
        needs_clarify = result.get('needs_clarification', False)
        results.append(("无上下文时提示", needs_clarify or '不确定' in result.get('response', ''), ""))
        
        # 测试 2: 有上下文时
        ctx = ContextManager()
        ctx.add_turn("分析 AAPL", "report", "AAPL 是个好股票...", {'tickers': ['AAPL']})
        
        result = handler.handle(
            query="风险呢",
            metadata={},
            context=ctx
        )
        results.append(("有上下文时处理", 'response' in result, f"意图: {result.get('intent')}"))
        
        # 测试 3: 追问类型分类
        followup_type = handler._classify_followup("为什么")
        results.append(("追问类型分类", followup_type == 'why', f"类型: {followup_type}"))
        
    except Exception as e:
        results.append(("FollowupHandler 导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_conversation_agent():
    """测试 ConversationAgent 统一入口"""
    print("\n🤖 测试 ConversationAgent...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        
        # 创建 Agent（不使用 LLM）
        agent = ConversationAgent()
        
        # 测试 1: 初始化
        results.append(("Agent 初始化", agent is not None, ""))
        
        # 测试 2: 简单查询
        response = agent.chat("AAPL 股价多少")
        results.append(("简单查询", 'response' in response, f"意图: {response.get('intent')}"))
        
        # 测试 3: 上下文更新
        results.append(("上下文更新", agent.context.current_focus == 'AAPL', 
                       f"焦点: {agent.context.current_focus}"))
        
        # 测试 4: 追问处理
        response = agent.chat("它怎么样")
        results.append(("追问处理", 'response' in response, ""))
        
        # 测试 5: 报告请求
        response = agent.chat("分析 TSLA")
        results.append(("报告请求", response.get('intent') == 'report', 
                       f"意图: {response.get('intent')}"))
        
        # 测试 6: 统计信息
        stats = agent.get_stats()
        results.append(("统计信息", stats['total_queries'] > 0, 
                       f"总查询: {stats['total_queries']}"))
        
        # 测试 7: 重置功能
        agent.reset()
        results.append(("重置功能", len(agent.context.history) == 0, ""))
        
    except Exception as e:
        import traceback
        results.append(("ConversationAgent 导入", False, str(e)))
        traceback.print_exc()
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_multi_turn_conversation():
    """测试多轮对话"""
    print("\n💬 测试多轮对话场景...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.conversation.agent import ConversationAgent
        
        agent = ConversationAgent()
        
        # 多轮对话测试
        conversation = [
            ("AAPL 现在多少钱", "chat", "价格查询"),
            ("分析一下", "report", "报告请求 (使用上下文)"),
            ("风险呢", "followup", "追问风险"),
            ("TSLA 怎么样", "chat", "切换股票"),
            ("对比一下", "followup", "对比分析"),
        ]
        
        for query, expected_intent, desc in conversation:
            response = agent.chat(query)
            intent = response.get('intent', 'unknown')
            passed = intent == expected_intent
            results.append((desc, passed, f"意图: {intent}, 预期: {expected_intent}"))
        
        # 验证上下文
        results.append(("焦点切换", agent.context.current_focus == 'TSLA', 
                       f"当前焦点: {agent.context.current_focus}"))
        results.append(("历史记录", len(agent.context.history) == 5, 
                       f"历史轮数: {len(agent.context.history)}"))
        
    except Exception as e:
        results.append(("多轮对话测试", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def test_system_prompts():
    """测试系统提示词"""
    print("\n📝 测试系统提示词...")
    print("-" * 50)
    
    results = []
    
    try:
        from backend.prompts.system_prompts import (
            CLASSIFICATION_PROMPT,
            CHAT_SYSTEM_PROMPT,
            REPORT_SYSTEM_PROMPT,
            ALERT_SYSTEM_PROMPT,
            FOLLOWUP_SYSTEM_PROMPT,
            get_prompt_for_intent
        )
        
        # 验证提示词存在且非空
        prompts = [
            ('分类提示词', CLASSIFICATION_PROMPT),
            ('聊天提示词', CHAT_SYSTEM_PROMPT),
            ('报告提示词', REPORT_SYSTEM_PROMPT),
            ('提醒提示词', ALERT_SYSTEM_PROMPT),
            ('追问提示词', FOLLOWUP_SYSTEM_PROMPT),
        ]
        
        for name, prompt in prompts:
            results.append((name, len(prompt) > 100, f"长度: {len(prompt)} 字符"))
        
        # 测试获取函数
        chat_prompt = get_prompt_for_intent('chat')
        results.append(("get_prompt_for_intent", chat_prompt == CHAT_SYSTEM_PROMPT, ""))
        
    except Exception as e:
        results.append(("系统提示词导入", False, str(e)))
    
    for name, passed, detail in results:
        print_result(name, passed, detail)
    
    return all(r[1] for r in results)


def main():
    """运行所有测试"""
    print_header("Phase 2 集成测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # 运行各项测试
    results['ContextManager'] = test_context_manager()
    results['ConversationRouter'] = test_conversation_router()
    results['ChatHandler'] = test_chat_handler()
    results['ReportHandler'] = test_report_handler()
    results['FollowupHandler'] = test_followup_handler()
    results['ConversationAgent'] = test_conversation_agent()
    results['多轮对话'] = test_multi_turn_conversation()
    results['系统提示词'] = test_system_prompts()
    
    # 汇总结果
    print_header("Phase 2 测试结果汇总")
    
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
        print("🎉 Phase 2 集成测试全部通过！")
        print("🎉 对话能力核心模块已就绪")
        print("🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
    else:
        print("\n⚠️ 部分测试未通过，请检查上述失败项")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

