#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangSmith 集成测试脚本
测试 langsmith_integration.py 的核心功能
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langsmith_integration import (
    RunContext,
    start_run,
    log_event,
    finish_run,
    is_enabled,
    get_status,
    trace_analysis,
    LangSmithCallbackMixin
)


class TestRunContext(unittest.TestCase):
    """测试 RunContext 数据结构"""
    
    def test_create_run_context(self):
        """测试创建运行上下文"""
        run = RunContext(
            run_id="test-123",
            name="Test Run",
            start_time=datetime.now(),
            metadata={"query": "test query"}
        )
        
        self.assertEqual(run.run_id, "test-123")
        self.assertEqual(run.name, "Test Run")
        self.assertEqual(run.status, "running")
        self.assertEqual(run.tool_calls, 0)
        self.assertIsNone(run.error)
    
    def test_to_dict(self):
        """测试转换为字典"""
        run = RunContext(
            run_id="test-456",
            name="Dict Test",
            start_time=datetime.now()
        )
        
        d = run.to_dict()
        
        self.assertIn("run_id", d)
        self.assertIn("name", d)
        self.assertIn("start_time", d)
        self.assertIn("status", d)


class TestRunTracking(unittest.TestCase):
    """测试运行追踪功能"""
    
    def test_start_run(self):
        """测试开始运行"""
        run = start_run(
            name="Test Analysis",
            query="分析 AAPL 股票",
            metadata={"source": "test"}
        )
        
        self.assertIsInstance(run, RunContext)
        self.assertIn("Test Analysis", run.name)
        self.assertEqual(run.status, "running")
    
    def test_log_event(self):
        """测试记录事件"""
        run = start_run(name="Event Test", query="test")
        
        log_event(run, "tool_start", {"tool": "get_stock_price"})
        log_event(run, "tool_end", {"output": "AAPL: $150"})
        
        self.assertEqual(len(run.events), 2)
        self.assertEqual(run.events[0]["type"], "tool_start")
        self.assertEqual(run.events[1]["type"], "tool_end")
        self.assertEqual(run.tool_calls, 1)  # tool_end 增加计数
    
    def test_finish_run_success(self):
        """测试成功完成运行"""
        run = start_run(name="Finish Test", query="test")
        log_event(run, "tool_end", {"output": "result"})
        
        summary = finish_run(
            run,
            status="success",
            outputs={"result": "Analysis complete"}
        )
        
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["tool_calls"], 1)
        self.assertIn("duration_seconds", summary)
    
    def test_finish_run_error(self):
        """测试错误完成运行"""
        run = start_run(name="Error Test", query="test")
        
        summary = finish_run(
            run,
            status="error",
            error="API timeout"
        )
        
        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["error"], "API timeout")


class TestCallbackMixin(unittest.TestCase):
    """测试回调混入类"""
    
    def test_mixin_lifecycle(self):
        """测试混入类的生命周期"""
        mixin = LangSmithCallbackMixin()
        
        # 开始
        mixin.langsmith_on_chain_start("分析 TSLA", {"test": True})
        
        # 工具调用
        mixin.langsmith_on_tool_start("get_price", "TSLA")
        mixin.langsmith_on_tool_end("get_price", "TSLA: $200")
        
        # LLM
        mixin.langsmith_on_llm_start(1)
        
        # 结束
        mixin.langsmith_on_chain_end(
            outputs={"result": "done"},
            success=True
        )


class TestDecorator(unittest.TestCase):
    """测试装饰器"""
    
    def test_trace_analysis_success(self):
        """测试成功分析的追踪"""
        @trace_analysis("Test Decorator")
        def mock_analysis(query: str) -> str:
            return f"Analysis of {query}"
        
        result = mock_analysis("NVDA")
        self.assertEqual(result, "Analysis of NVDA")
    
    def test_trace_analysis_error(self):
        """测试错误分析的追踪"""
        @trace_analysis("Error Test")
        def failing_analysis(query: str) -> str:
            raise ValueError("Test error")
        
        with self.assertRaises(ValueError):
            failing_analysis("FAIL")


class TestConfiguration(unittest.TestCase):
    """测试配置"""
    
    def test_get_status(self):
        """测试获取状态"""
        status = get_status()
        
        self.assertIn("enabled", status)
        self.assertIn("initialized", status)
        self.assertIn("project", status)
        self.assertIn("has_api_key", status)
    
    def test_is_enabled_without_init(self):
        """测试未初始化时的状态"""
        # 默认未初始化应返回 False
        # 注意：如果环境变量设置了，可能返回 True
        result = is_enabled()
        self.assertIsInstance(result, bool)


class TestIntegrationWithStreaming(unittest.TestCase):
    """测试与 streaming_support 的集成"""
    
    def test_import_in_streaming(self):
        """测试在 streaming_support 中的导入"""
        try:
            from streaming_support import FinancialStreamingCallbackHandler
            handler = FinancialStreamingCallbackHandler()
            
            # 检查 LangSmith 相关属性
            self.assertTrue(hasattr(handler, '_langsmith_run'))
            self.assertTrue(hasattr(handler, '_current_query'))
            
        except ImportError as e:
            self.skipTest(f"streaming_support 不可用: {e}")


def run_quick_test():
    """快速功能测试（无需 unittest）"""
    print("=" * 60)
    print("🧪 LangSmith 集成快速测试")
    print("=" * 60)
    
    # 1. 测试状态
    print("\n1️⃣ 检查状态...")
    status = get_status()
    print(f"   状态: {status}")
    
    # 2. 测试运行追踪
    print("\n2️⃣ 测试运行追踪...")
    run = start_run(
        name="Quick Test",
        query="测试查询",
        metadata={"source": "quick_test"}
    )
    print(f"   创建运行: {run.run_id[:8]}...")
    
    # 3. 测试事件记录
    print("\n3️⃣ 测试事件记录...")
    log_event(run, "tool_start", {"tool": "test_tool"})
    log_event(run, "tool_end", {"output": "test output"})
    print(f"   记录事件: {len(run.events)} 个")
    print(f"   工具调用: {run.tool_calls} 次")
    
    # 4. 测试完成运行
    print("\n4️⃣ 测试完成运行...")
    summary = finish_run(run, status="success", outputs={"test": True})
    print(f"   摘要: {summary}")
    
    # 5. 测试装饰器
    print("\n5️⃣ 测试装饰器...")
    @trace_analysis("Decorator Test")
    def sample_analysis(query: str) -> str:
        return f"结果: {query}"
    
    result = sample_analysis("测试查询")
    print(f"   装饰器结果: {result}")
    
    # 6. 测试回调混入
    print("\n6️⃣ 测试回调混入...")
    mixin = LangSmithCallbackMixin()
    mixin.langsmith_on_chain_start("测试", {})
    mixin.langsmith_on_chain_end(success=True)
    print("   回调混入: OK")
    
    print("\n" + "=" * 60)
    print("✅ 所有快速测试通过!")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LangSmith 集成测试")
    parser.add_argument("--quick", action="store_true", help="运行快速测试")
    parser.add_argument("--full", action="store_true", help="运行完整单元测试")
    
    args = parser.parse_args()
    
    if args.quick or (not args.full and not args.quick):
        # 默认运行快速测试
        run_quick_test()
    
    if args.full:
        # 运行完整单元测试
        unittest.main(argv=[''], exit=False, verbosity=2)
