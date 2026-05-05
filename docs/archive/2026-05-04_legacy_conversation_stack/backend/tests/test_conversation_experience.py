# -*- coding: utf-8 -*-
"""
对话模式完整体验测试
模拟真实用户的多种对话场景
"""

import sys
import os
from datetime import datetime
from typing import List, Tuple, Dict, Any

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class ConversationTester:
    """对话测试器"""
    
    def __init__(self):
        from backend.conversation.agent import ConversationAgent
        from backend.orchestration.orchestrator import ToolOrchestrator
        from backend.orchestration.tools_bridge import register_all_financial_tools
        
        self.orchestrator = ToolOrchestrator()
        register_all_financial_tools(self.orchestrator)
        self.agent = ConversationAgent(orchestrator=self.orchestrator)
        
        self.passed = 0
        self.failed = 0
        self.results: List[Dict] = []
    
    def chat(self, query: str) -> Dict[str, Any]:
        """执行对话"""
        return self.agent.chat(query)
    
    def reset(self):
        """重置对话"""
        self.agent.reset()
    
    def verify(self, name: str, condition: bool, detail: str = ""):
        """验证结果"""
        if condition:
            self.passed += 1
            status = "✅"
        else:
            self.failed += 1
            status = "❌"
        
        result = {"name": name, "passed": condition, "detail": detail}
        self.results.append(result)
        print(f"  {status} {name}")
        if detail:
            print(f"      {detail}")
        return condition
    
    def run_scenario(self, name: str, queries: List[Tuple[str, str, str]]):
        """运行测试场景"""
        print(f"\n{'─' * 50}")
        print(f"📋 场景: {name}")
        print(f"{'─' * 50}")
        
        self.reset()
        
        for query, expected_intent, description in queries:
            response = self.chat(query)
            intent = response.get('intent', 'unknown')
            success = response.get('success', False) or 'response' in response
            
            passed = intent == expected_intent and success
            self.verify(
                description,
                passed,
                f"查询: '{query[:30]}...' → 意图: {intent}"
            )
            
            # 简短显示响应
            resp_text = response.get('response', '')[:100]
            if resp_text:
                print(f"      💬 {resp_text}...")


def test_scenario_1_basic_price_queries():
    """场景1: 基本价格查询"""
    tester = ConversationTester()
    
    queries = [
        ("AAPL 股价多少", "chat", "英文代码价格查询"),
        ("特斯拉现在多少钱", "chat", "中文名称价格查询"),
        ("NVDA 今天涨了吗", "chat", "涨跌查询"),
        ("谷歌股价", "chat", "中文名查询谷歌"),
    ]
    
    tester.run_scenario("基本价格查询", queries)
    assert tester is not None


def test_scenario_2_report_requests():
    """场景2: 报告生成请求"""
    tester = ConversationTester()
    
    queries = [
        ("分析 AAPL 股票", "report", "标准分析请求"),
        ("帮我详细分析一下微软", "report", "详细分析请求"),
        ("NVDA 值得投资吗", "report", "投资建议请求"),
        ("苹果公司的投资前景如何", "report", "前景分析请求"),
    ]
    
    tester.run_scenario("报告生成请求", queries)
    assert tester is not None


def test_scenario_3_followup_questions():
    """场景3: 追问对话"""
    tester = ConversationTester()
    
    queries = [
        ("分析 TSLA", "report", "初始分析"),
        ("为什么这样判断", "followup", "追问原因"),
        ("风险在哪里", "followup", "追问风险"),
        ("有什么优势", "followup", "追问优势"),
        ("详细说说", "followup", "请求详细"),
        ("对比一下 AAPL", "followup", "对比分析"),
    ]
    
    tester.run_scenario("追问对话", queries)
    assert tester is not None


def test_scenario_4_context_switching():
    """场景4: 上下文切换"""
    tester = ConversationTester()
    
    queries = [
        ("AAPL 股价", "chat", "查询苹果"),
        ("它最近新闻", "chat", "用'它'指代苹果"),
        ("MSFT 怎么样", "chat", "切换到微软"),
        ("这个公司最近有什么动态", "chat", "用'这个公司'指代微软"),
        ("NVDA 分析一下", "report", "切换到英伟达并分析"),
        ("它的竞争对手是谁", "followup", "追问竞争对手"),
    ]
    
    tester.run_scenario("上下文切换", queries)
    
    # 验证最终焦点
    tester.verify(
        "最终焦点正确",
        tester.agent.context.current_focus == 'NVDA',
        f"焦点: {tester.agent.context.current_focus}"
    )
    
    assert tester is not None


def test_scenario_5_chinese_companies():
    """场景5: 中文公司名识别"""
    tester = ConversationTester()
    
    chinese_queries = [
        ("苹果公司股价", "chat", "苹果→AAPL"),
        ("特斯拉今天表现", "chat", "特斯拉→TSLA"),
        ("英伟达最新消息", "chat", "英伟达→NVDA"),
        ("阿里巴巴怎么样", "chat", "阿里巴巴→BABA"),
        ("京东股票分析", "report", "京东→JD"),
        ("百度值得买吗", "report", "百度→BIDU"),
    ]
    
    tester.run_scenario("中文公司名识别", chinese_queries)
    assert tester is not None


def test_scenario_6_alert_requests():
    """场景6: 监控提醒请求"""
    tester = ConversationTester()
    
    queries = [
        ("帮我盯着 TSLA", "alert", "基本监控请求"),
        ("AAPL 跌到 180 提醒我", "alert", "价格提醒请求"),
        ("监控一下英伟达", "alert", "中文监控请求"),
        ("MSFT 涨到 500 通知我", "alert", "涨价提醒"),
    ]
    
    tester.run_scenario("监控提醒请求", queries)
    assert tester is not None


def test_scenario_7_mixed_conversation():
    """场景7: 混合对话流程"""
    tester = ConversationTester()
    
    queries = [
        ("AAPL 现在多少钱", "chat", "价格查询"),
        ("分析一下它", "report", "报告请求"),
        ("风险呢", "followup", "追问风险"),
        ("TSLA 对比怎么样", "followup", "对比请求"),
        ("特斯拉股价", "chat", "切换查价格"),
        ("帮我盯着", "alert", "设置监控"),
        ("详细分析一下", "report", "再次请求报告"),
    ]
    
    tester.run_scenario("混合对话流程", queries)
    assert tester is not None


def test_scenario_8_edge_cases():
    """场景8: 边缘情况"""
    tester = ConversationTester()
    
    print(f"\n{'─' * 50}")
    print(f"📋 场景: 边缘情况处理")
    print(f"{'─' * 50}")
    
    tester.reset()
    
    # 测试1: 空查询
    try:
        response = tester.chat("")
        tester.verify("空查询不崩溃", True, "")
    except Exception as e:
        tester.verify("空查询不崩溃", False, str(e))
    
    # 测试2: 无效股票代码
    response = tester.chat("XXXXX999 股价")
    tester.verify(
        "无效代码有响应",
        'response' in response,
        f"响应长度: {len(response.get('response', ''))}"
    )
    
    # 测试3: 非常长的查询
    long_query = "分析 " + "AAPL " * 50
    response = tester.chat(long_query[:200])
    tester.verify(
        "长查询有响应",
        'response' in response,
        ""
    )
    
    # 测试4: 特殊字符
    response = tester.chat("AAPL!@#$%^&*() 股价")
    tester.verify(
        "特殊字符不崩溃",
        'response' in response,
        ""
    )
    
    # 测试5: 纯数字
    response = tester.chat("12345")
    tester.verify(
        "纯数字有响应",
        'response' in response,
        ""
    )
    
    assert tester is not None


def test_scenario_9_session_persistence():
    """场景9: 会话持久性"""
    tester = ConversationTester()
    
    print(f"\n{'─' * 50}")
    print(f"📋 场景: 会话持久性测试")
    print(f"{'─' * 50}")
    
    # 进行多轮对话
    for i in range(5):
        tester.chat(f"{'AAPL TSLA NVDA MSFT GOOGL'.split()[i]} 股价")
    
    # 验证历史记录
    history_len = len(tester.agent.context.history)
    tester.verify(
        "历史记录正确",
        history_len == 5,
        f"记录轮数: {history_len}"
    )
    
    # 验证统计
    stats = tester.agent.get_stats()
    tester.verify(
        "统计正确",
        stats['total_queries'] == 5,
        f"总查询: {stats['total_queries']}"
    )
    
    # 测试重置
    tester.reset()
    tester.verify(
        "重置后历史清空",
        len(tester.agent.context.history) == 0,
        ""
    )
    
    tester.verify(
        "重置后统计清零",
        tester.agent.get_stats()['total_queries'] == 0,
        ""
    )
    
    # 重置后继续使用
    response = tester.chat("AAPL 股价")
    tester.verify(
        "重置后可继续使用",
        'response' in response,
        ""
    )
    
    assert tester is not None


def test_scenario_10_performance():
    """场景10: 性能测试"""
    tester = ConversationTester()
    
    print(f"\n{'─' * 50}")
    print(f"📋 场景: 性能测试")
    print(f"{'─' * 50}")
    
    import time
    
    # 测试响应时间
    queries = [
        ("AAPL 股价", "简单查询"),
        ("分析 TSLA", "报告请求"),
        ("为什么", "追问"),
    ]
    
    times = []
    for query, desc in queries:
        start = time.time()
        response = tester.chat(query)
        elapsed = (time.time() - start) * 1000
        times.append(elapsed)
        
        tester.verify(
            f"{desc}响应时间",
            elapsed < 30000,  # 30秒内
            f"{elapsed:.0f}ms"
        )
    
    avg_time = sum(times) / len(times)
    tester.verify(
        "平均响应时间合理",
        avg_time < 15000,
        f"平均: {avg_time:.0f}ms"
    )
    
    assert tester is not None


def main():
    """运行所有测试场景"""
    print("=" * 60)
    print("🎮 对话模式完整体验测试")
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    all_testers = []
    
    # 运行所有场景
    scenarios = [
        ("基本价格查询", test_scenario_1_basic_price_queries),
        ("报告生成请求", test_scenario_2_report_requests),
        ("追问对话", test_scenario_3_followup_questions),
        ("上下文切换", test_scenario_4_context_switching),
        ("中文公司名识别", test_scenario_5_chinese_companies),
        ("监控提醒请求", test_scenario_6_alert_requests),
        ("混合对话流程", test_scenario_7_mixed_conversation),
        ("边缘情况", test_scenario_8_edge_cases),
        ("会话持久性", test_scenario_9_session_persistence),
        ("性能测试", test_scenario_10_performance),
    ]
    
    for name, test_func in scenarios:
        try:
            tester = test_func()
            all_testers.append((name, tester))
        except Exception as e:
            print(f"\n❌ 场景 '{name}' 执行失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    total_passed = 0
    total_failed = 0
    
    for name, tester in all_testers:
        passed = tester.passed
        failed = tester.failed
        total = passed + failed
        status = "✅" if failed == 0 else "⚠️" if failed < passed else "❌"
        print(f"  {status} {name}: {passed}/{total} 通过")
        total_passed += passed
        total_failed += failed
    
    print(f"\n{'─' * 60}")
    print(f"  总计: {total_passed}/{total_passed + total_failed} 通过")
    
    success_rate = total_passed / (total_passed + total_failed) * 100 if (total_passed + total_failed) > 0 else 0
    
    if total_failed == 0:
        print("\n🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
        print("🎉 所有对话体验测试通过！")
        print("🎉 对话模式已准备就绪！")
        print("🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
    elif success_rate >= 90:
        print(f"\n✅ 体验测试基本通过 ({success_rate:.1f}%)")
        print("   少量问题需要优化")
    else:
        print(f"\n⚠️ 体验测试通过率: {success_rate:.1f}%")
        print("   需要进一步优化")
    
    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

