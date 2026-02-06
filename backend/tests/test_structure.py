# -*- coding: utf-8 -*-
"""
Step 1.1 测试 - 验证目录结构
确保所有模块可以正确导入
"""

import sys
import os
import pytest

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


def test_backend_package():
    """测试 backend 包可以导入"""
    try:
        import backend
        assert hasattr(backend, '__version__')
        print("✅ backend 包导入成功")
    except ImportError as e:
        pytest.fail(f"backend 包导入失败: {e}")


def test_orchestration_module():
    """测试 orchestration 模块"""
    try:
        from backend.orchestration import DataCache, DataValidator, ValidationResult
        
        # 测试 DataCache 实例化
        cache = DataCache()
        assert cache is not None
        
        # 测试基本功能
        cache.set("test_key", {"value": 123}, data_type="default")
        result = cache.get("test_key")
        assert result is not None
        assert result["value"] == 123
        
        # 测试 DataValidator 实例化
        validator = DataValidator()
        assert validator is not None
        
        print("✅ orchestration 模块测试通过")
    except Exception as e:
        pytest.fail(f"orchestration 模块测试失败: {e}")


def test_conversation_module():
    """测试 conversation 模块"""
    try:
        from backend.conversation import ContextManager, ConversationTurn, ConversationRouter, Intent
        
        # 测试 ContextManager 实例化
        context = ContextManager()
        assert context is not None
        
        # 测试添加对话轮次
        turn = context.add_turn("测试查询", "chat")
        assert turn is not None
        assert turn.query == "测试查询"
        
        # 测试 Intent 枚举
        assert Intent.CHAT.value == "chat"
        assert Intent.REPORT.value == "report"
        
        # 测试 ConversationRouter 实例化（不带 LLM）
        router = ConversationRouter()
        assert router is not None
        
        # 测试意图分类
        intent, metadata = router.classify_intent("AAPL 股价多少")
        assert intent == Intent.CHAT
        assert "AAPL" in metadata.get('tickers', [])
        
        print("✅ conversation 模块测试通过")
    except Exception as e:
        pytest.fail(f"conversation 模块测试失败: {e}")


def test_handlers_module():
    """测试 handlers 模块"""
    try:
        from backend.handlers import ChatHandler, FollowupHandler
        
        # 测试实例化
        chat_handler = ChatHandler()
        assert chat_handler is not None
        
        # NOTE: ReportHandler 已废弃，移除测试
        
        followup_handler = FollowupHandler()
        assert followup_handler is not None
        
        print("✅ handlers 模块测试通过")
    except Exception as e:
        pytest.fail(f"handlers 模块测试失败: {e}")


def test_prompts_module():
    """测试 prompts 模块"""
    try:
        from backend.prompts import (
            FORUM_SYNTHESIS_PROMPT,
            FOLLOWUP_SYSTEM_PROMPT,
        )
        
        # 验证提示词不为空
        assert len(FORUM_SYNTHESIS_PROMPT) > 100
        assert len(FOLLOWUP_SYSTEM_PROMPT) > 100
        
        # 验证包含关键占位符
        assert "{query}" in FOLLOWUP_SYSTEM_PROMPT
        assert "{risk_tolerance}" in FORUM_SYNTHESIS_PROMPT
        
        print("✅ prompts 模块测试通过")
    except Exception as e:
        pytest.fail(f"prompts 模块测试失败: {e}")


def test_directory_structure():
    """验证目录结构"""
    required_dirs = [
        "backend",
        "backend/orchestration",
        "backend/conversation", 
        "backend/handlers",
        "backend/prompts",
        "backend/tests",
        "backend/api",
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        full_path = os.path.join(PROJECT_ROOT, dir_path)
        if os.path.isdir(full_path):
            print(f"✅ 目录存在: {dir_path}")
        else:
            print(f"❌ 目录缺失: {dir_path}")
            all_exist = False
    
    assert all_exist, "目录结构缺失，请检查上方日志"


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Step 1.1 测试 - 验证目录结构和模块导入")
    print("=" * 60)
    print()
    
    results = {}
    tests = [
        ("目录结构", test_directory_structure),
        ("backend 包", test_backend_package),
        ("orchestration 模块", test_orchestration_module),
        ("conversation 模块", test_conversation_module),
        ("handlers 模块", test_handlers_module),
        ("prompts 模块", test_prompts_module),
    ]

    for test_name, test_func in tests:
        try:
            test_func()
            results[test_name] = True
        except Exception:
            results[test_name] = False
    
    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    print()
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 Step 1.1 测试全部通过！可以继续下一步。")
        return True
    else:
        print("\n⚠️ 部分测试失败，请修复后再继续。")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

