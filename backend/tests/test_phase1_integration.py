# -*- coding: utf-8 -*-
"""
Phase 1 集成测试
验证整个 Orchestration 层与真实 backend.tools 的集成
"""

import sys
import os
import time

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


# ============================================
# 测试用例
# ============================================

def test_tools_module_import():
    """测试 tools 模块可以导入"""
    try:
        from backend import tools
        
        # 检查关键函数存在
        assert hasattr(tools, 'get_stock_price')
        assert hasattr(tools, 'get_company_info')
        assert hasattr(tools, 'get_company_news')
        assert hasattr(tools, 'search')
        
        print("✅ tools 模块导入测试通过")
        return True
    except Exception as e:
        print(f"❌ tools 模块导入失败: {e}")
        return False


def test_orchestrator_with_tools():
    """测试 Orchestrator 与 tools 集成"""
    try:
        from backend.orchestration.tools_bridge import create_orchestrator_with_tools
        
        orchestrator = create_orchestrator_with_tools()
        
        # 验证数据源已配置
        assert 'price' in orchestrator.sources
        assert len(orchestrator.sources['price']) > 0
        
        print(f"✅ Orchestrator 已配置 {len(orchestrator.sources['price'])} 个价格数据源")
        return True
    except Exception as e:
        print(f"❌ Orchestrator 集成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_single_stock_price(ticker: str) -> dict:
    """
    测试单个股票的价格获取
    
    Returns:
        包含测试结果的字典
    """
    from backend.orchestration.tools_bridge import get_global_orchestrator
    
    result = {
        'ticker': ticker,
        'success': False,
        'source': None,
        'cached': False,
        'data': None,
        'error': None,
        'duration_ms': 0,
    }
    
    try:
        orchestrator = get_global_orchestrator()
        fetch_result = orchestrator.fetch('price', ticker)
        
        result['success'] = fetch_result.success
        result['source'] = fetch_result.source
        result['cached'] = fetch_result.cached
        result['data'] = fetch_result.data[:100] if fetch_result.data else None
        result['error'] = fetch_result.error
        result['duration_ms'] = fetch_result.duration_ms
        
        if fetch_result.success:
            print(f"  ✅ {ticker}: 成功 (源: {fetch_result.source}, "
                  f"{'缓存' if fetch_result.cached else '实时'}, "
                  f"{fetch_result.duration_ms:.0f}ms)")
        else:
            print(f"  ❌ {ticker}: 失败 - {fetch_result.error}")
        
    except Exception as e:
        result['error'] = str(e)
        print(f"  ❌ {ticker}: 异常 - {e}")
    
    return result


def test_five_representative_stocks():
    """测试 5 个代表性股票"""
    print("\n📊 测试 5 个代表性股票...")
    print("-" * 50)
    
    # 代表性股票：美股科技 + ETF + 中概股
    test_tickers = ['AAPL', 'GOOGL', 'TSLA', 'SPY', 'BABA']
    
    results = []
    for ticker in test_tickers:
        result = test_single_stock_price(ticker)
        results.append(result)
        time.sleep(1)  # 避免请求过快
    
    # 统计
    success_count = sum(1 for r in results if r['success'])
    
    print("-" * 50)
    print(f"\n📈 成功率: {success_count}/{len(test_tickers)} ({success_count/len(test_tickers)*100:.0f}%)")
    
    # 验收标准：至少 4/5 成功
    passed = success_count >= 4
    
    if passed:
        print("✅ 5 个代表性股票测试通过 (≥80% 成功)")
    else:
        print("❌ 5 个代表性股票测试失败 (<80% 成功)")
    
    return passed


def test_cache_effectiveness():
    """测试缓存有效性"""
    print("\n🗄️ 测试缓存有效性...")
    print("-" * 50)
    
    from backend.orchestration.tools_bridge import get_global_orchestrator
    
    orchestrator = get_global_orchestrator()
    ticker = 'AAPL'
    
    # 第一次获取（应该是实时）
    result1 = orchestrator.fetch('price', ticker)
    is_first_cached = result1.cached
    first_duration = result1.duration_ms
    
    print(f"  第一次获取: {'缓存' if result1.cached else '实时'}, {result1.duration_ms:.0f}ms")
    
    # 第二次获取（应该是缓存）
    result2 = orchestrator.fetch('price', ticker)
    is_second_cached = result2.cached
    second_duration = result2.duration_ms
    
    print(f"  第二次获取: {'缓存' if result2.cached else '实时'}, {result2.duration_ms:.0f}ms")
    
    # 验证
    passed = True
    
    # 如果第一次成功，第二次应该是缓存
    if result1.success:
        if not result2.cached:
            print("  ⚠️ 警告: 第二次获取应该使用缓存")
            passed = False
        else:
            print("  ✅ 缓存命中正确")
    
    # 缓存获取应该更快
    if result2.cached and second_duration > first_duration:
        print("  ⚠️ 警告: 缓存获取不应该比实时获取慢")
    else:
        print("  ✅ 缓存性能正常")
    
    if passed:
        print("✅ 缓存有效性测试通过")
    
    return passed


def test_fallback_mechanism():
    """测试回退机制"""
    print("\n🔄 测试回退机制...")
    print("-" * 50)
    
    from backend.orchestration.tools_bridge import get_global_orchestrator
    
    orchestrator = get_global_orchestrator()
    
    # 获取统计信息
    stats = orchestrator.get_stats()
    
    print(f"  总请求: {stats['orchestrator']['total_requests']}")
    print(f"  缓存命中: {stats['orchestrator']['cache_hits']}")
    print(f"  回退使用: {stats['orchestrator']['fallback_used']}")
    print(f"  总失败: {stats['orchestrator']['total_failures']}")
    
    # 打印数据源状态
    if 'price' in stats['sources']:
        print("\n  数据源状态:")
        for source in stats['sources']['price']:
            print(f"    - {source['name']}: 调用 {source['total_calls']} 次, "
                  f"成功率 {source['success_rate']}")
    
    print("✅ 回退机制状态检查完成")
    return True


def test_conversation_router():
    """测试对话路由器"""
    print("\n🧭 测试对话路由器...")
    print("-" * 50)
    
    from backend.conversation import ConversationRouter, Intent
    
    router = ConversationRouter()
    
    test_cases = [
        ("AAPL 股价多少", Intent.CHAT),
        ("分析苹果公司股票", Intent.REPORT),
        ("帮我盯着 NVDA", Intent.ALERT),
        ("为什么呢", Intent.FOLLOWUP),
    ]
    
    passed = 0
    for query, expected_intent in test_cases:
        intent, metadata = router.classify_intent(query)
        is_correct = intent == expected_intent
        status = "✅" if is_correct else "❌"
        print(f"  {status} '{query}' -> {intent.value} (期望: {expected_intent.value})")
        if is_correct:
            passed += 1
    
    success_rate = passed / len(test_cases)
    
    if success_rate >= 0.75:
        print(f"✅ 对话路由器测试通过 ({passed}/{len(test_cases)})")
        return True
    else:
        print(f"❌ 对话路由器测试失败 ({passed}/{len(test_cases)})")
        return False


def test_context_manager():
    """测试上下文管理器"""
    print("\n📝 测试上下文管理器...")
    print("-" * 50)
    
    from backend.conversation import ContextManager
    
    context = ContextManager()
    
    # 添加对话轮次
    context.add_turn("AAPL 股价多少", "chat", metadata={'tickers': ['AAPL']})
    context.add_turn("为什么涨了", "followup")
    
    # 验证
    assert len(context.history) == 2, "应该有 2 轮对话"
    assert context.current_focus == 'AAPL', "当前焦点应该是 AAPL"
    
    # 测试指代词解析
    resolved = context.resolve_reference("它怎么样")
    assert "AAPL" in resolved, "应该解析指代词为 AAPL"
    
    print(f"  ✅ 对话历史: {len(context.history)} 轮")
    print(f"  ✅ 当前焦点: {context.current_focus}")
    print(f"  ✅ 指代解析: '它怎么样' -> '{resolved}'")
    print("✅ 上下文管理器测试通过")
    
    return True


def run_phase1_integration_tests():
    """运行 Phase 1 集成测试"""
    print("=" * 60)
    print("Phase 1 集成测试")
    print("=" * 60)
    
    tests = [
        ("Tools 模块导入", test_tools_module_import),
        ("Orchestrator 集成", test_orchestrator_with_tools),
        ("5 个代表性股票", test_five_representative_stocks),
        ("缓存有效性", test_cache_effectiveness),
        ("回退机制", test_fallback_mechanism),
        ("对话路由器", test_conversation_router),
        ("上下文管理器", test_context_manager),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = False
        print()
    
    print("=" * 60)
    print("Phase 1 测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    print()
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n" + "🎉" * 20)
        print("🎉 Phase 1 集成测试全部通过！")
        print("🎉 可以继续 Phase 2: 对话能力开发")
        print("🎉" * 20)
        return True
    else:
        print("\n⚠️ 部分测试失败，请修复后再继续。")
        return False


if __name__ == "__main__":
    success = run_phase1_integration_tests()
    sys.exit(0 if success else 1)

