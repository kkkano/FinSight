#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试流式输出功能
"""

from langchain_agent import create_financial_agent
from streaming_support import AsyncFinancialStreamer, FinancialDashboard, ProgressIndicator

def test_basic_streaming():
    """测试基础流式输出"""
    print("="*70)
    print("测试 1: 基础流式输出")
    print("="*70)
    
    # 创建 agent
    agent = create_financial_agent(verbose=False)
    
    # 创建流式输出器
    streamer = AsyncFinancialStreamer(show_progress=True, show_details=True)
    
    # 执行流式分析
    query = "获取 AAPL 的当前股价"
    result = streamer.stream_analysis(agent, query)
    
    print("\n分析结果:")
    print(result.get("output", "无输出")[:500])
    

def test_progress_indicator():
    """测试进度指示器"""
    print("\n" + "="*70)
    print("测试 2: 进度指示器")
    print("="*70)
    
    progress = ProgressIndicator(total_steps=5)
    progress.start("测试进度条")
    
    import time
    steps = ["初始化", "数据加载", "数据处理", "生成报告", "完成"]
    for step in steps:
        time.sleep(0.5)
        progress.update(step)
    
    progress.finish(success=True)


def test_dashboard():
    """测试仪表板"""
    print("\n" + "="*70)
    print("测试 3: 分析仪表板")
    print("="*70)
    
    dashboard = FinancialDashboard()
    
    # 模拟一些分析记录
    dashboard.record_analysis("分析 AAPL", True, 12.5, 5)
    dashboard.record_analysis("分析 NVDA", True, 15.3, 6)
    dashboard.record_analysis("分析 MSFT", False, 8.2, 3)
    
    # 显示仪表板
    dashboard.display_dashboard()
    
    # 获取指标
    metrics = dashboard.get_metrics()
    print("指标统计:")
    print(f"  成功率: {metrics['success_rate']:.1f}%")
    print(f"  平均耗时: {metrics['avg_duration']:.2f}秒")


def main():
    """主测试函数"""
    print("\n🎯 FinSight 流式输出功能测试\n")
    
    # 测试 1: 基础流式输出
    try:
        test_basic_streaming()
    except Exception as e:
        print(f"❌ 测试 1 失败: {e}")
    
    # 测试 2: 进度指示器
    try:
        test_progress_indicator()
    except Exception as e:
        print(f"❌ 测试 2 失败: {e}")
    
    # 测试 3: 仪表板
    try:
        test_dashboard()
    except Exception as e:
        print(f"❌ 测试 3 失败: {e}")
    
    print("\n✅ 所有测试完成！\n")


if __name__ == "__main__":
    main()
