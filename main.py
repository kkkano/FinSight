#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinSight AI金融分析主程序
使用LangChain 1.0.1框架的最新版本
支持流式输出和实时进度显示
"""

import sys
import os
import argparse
import asyncio
from typing import Optional
from datetime import datetime

# 设置UTF-8编码
if sys.platform.startswith('win'):
    import locale
    import codecs
    # 设置控制台编码为UTF-8
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 导入LangChain组件
from langchain_agent import create_financial_agent, LangChainFinancialAgent
try:
    from streaming_support import AsyncFinancialStreamer, FinancialDashboard
except ImportError:
    print("警告: streaming_support 模块未找到，将使用基础模式")
    AsyncFinancialStreamer = None
    FinancialDashboard = None

def print_banner():
    """打印程序横幅"""
    print("=" * 80)
    print("FinSight AI - 智能金融分析系统")
    print("LangChain 1.0.1驱动 | 实时流式分析 | 专业投资报告")
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

def print_help():
    """打印帮助信息"""
    print("\n使用说明:")
    print("  直接运行: 进入交互模式")
    print("  查询分析: python main.py '分析AAPL股票'")
    print("  流式模式: python main.py '分析TSLA' --streaming")
    print("  批处理模式: python main.py 'AAPL MSFT GOOGL' --batch")
    print("  退出程序: 输入 'exit' 或按 Ctrl+C")
    print("\n示例查询:")
    print("  - '分析苹果公司股票'")
    print("  - 'Compare AAPL vs MSFT'")
    print("  - '市场指数表现如何'")
    print("  - '特斯拉值得投资吗'")

def create_agent_with_config(provider: str = "gemini_proxy",
                           model: str = "gemini-2.5-flash-preview-05-20",
                           streaming: bool = False) -> LangChainFinancialAgent:
    """创建配置好的Agent实例

    Args:
        provider: LLM提供商
        model: 模型名称
        streaming: 是否启用流式模式

    Returns:
        配置好的Agent实例
    """
    try:
        agent = create_financial_agent(
            provider=provider,
            model=model,
            verbose=True,
            max_iterations=15,
            show_intermediate_steps=True
        )

        print(f"Agent创建成功 | 提供商: {provider} | 模型: {model}")
        return agent

    except Exception as e:
        print(f"Agent创建失败: {str(e)}")
        print("请检查API密钥配置和网络连接")
        sys.exit(1)

def run_streaming_analysis(agent: LangChainFinancialAgent, query: str) -> str:
    """运行流式分析

    Args:
        agent: Agent实例
        query: 分析查询

    Returns:
        分析结果
    """
    try:
        # 如果有流式输出器，使用流式分析
        if AsyncFinancialStreamer is not None:
            streamer = AsyncFinancialStreamer(
                show_progress=True,
                show_details=True
            )

            # 执行流式分析
            if hasattr(streamer, 'stream_analysis'):
                result = streamer.sync_stream_analysis(agent, query)
            else:
                result = agent.analyze(query)
        else:
            # 没有流式支持，直接使用agent分析
            print("\n[开始分析]")
            result = agent.analyze(query)
            print("[分析完成]\n")

        return result

    except Exception as e:
        print(f"分析失败: {str(e)}")
        return f"分析失败: {str(e)}"

def run_interactive_mode(agent: LangChainFinancialAgent, use_streaming: bool = False):
    """运行交互模式

    Args:
        agent: Agent实例
        use_streaming: 是否使用流式模式
    """
    print("\n🎯 FinSight AI 交互模式")
    print("💡 请输入您的投资分析问题，输入 'exit' 退出程序")
    print("─" * 60)

    # 创建仪表板
    dashboard = FinancialDashboard()

    while True:
        try:
            query = input("\n🔍 请输入查询: ").strip()

            if query.lower() in ['exit', 'quit', '退出', 'q']:
                print("\n👋 感谢使用FinSight AI，祝您投资顺利！")
                break

            if not query:
                continue

            print(f"\n正在分析: {query}")
            print("-" * 60)

            # 开始分析
            dashboard.start_analysis(query)

            try:
                if use_streaming:
                    # 异步流式分析
                    result = asyncio.run(run_streaming_analysis(agent, query))
                else:
                    # 同步分析
                    result = agent.analyze(query)

                # 完成分析
                dashboard.finish_analysis(result, success=True)

                # 显示结果
                print("\n分析报告:")
                print("-" * 60)
                print(result)

            except Exception as e:
                dashboard.finish_analysis(str(e), success=False)
                print(f"分析失败: {str(e)}")

            print("\n" + "-" * 60)

        except KeyboardInterrupt:
            print("\n\n程序被用户中断，再见！")
            break
        except Exception as e:
            print(f"\n程序错误: {str(e)}")
            continue

def run_batch_mode(agent: LangChainFinancialAgent, queries: list, use_streaming: bool = False):
    """运行批处理模式

    Args:
        agent: Agent实例
        queries: 查询列表
        use_streaming: 是否使用流式模式
    """
    print(f"\n批处理模式 - 共{len(queries)}个查询")
    print("-" * 60)

    dashboard = FinancialDashboard()

    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] 正在分析: {query}")
        print("-" * 40)

        dashboard.start_analysis(query)

        try:
            if use_streaming:
                result = asyncio.run(run_streaming_analysis(agent, query))
            else:
                result = agent.analyze(query)

            dashboard.finish_analysis(result, success=True)

            # 显示结果摘要
            print(f"分析完成 - 报告长度: {len(result)} 字符")
            if len(result) > 200:
                print(f"摘要: {result[:200]}...")
            else:
                print(f"结果: {result}")

        except Exception as e:
            dashboard.finish_analysis(str(e), success=False)
            print(f"分析失败: {str(e)}")

        if i < len(queries):
            print("\n" + "." * 40)

    print(f"\n批处理完成 - 共处理{len(queries)}个查询")

    # 显示仪表板统计
    dashboard.display_dashboard()

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="FinSight AI - 智能金融分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python main.py                           # 交互模式
  python main.py "分析AAPL股票"            # 单次查询
  python main.py "AAPL MSFT" --batch       # 批处理模式
  python main.py "TSLA" --streaming        # 流式模式
  python main.py "NVDA" --provider openai  # 指定提供商
        """
    )

    parser.add_argument("query", nargs="?", help="分析查询内容")
    parser.add_argument("--batch", action="store_true", help="批处理模式")
    parser.add_argument("--streaming", action="store_true", help="启用流式输出")
    parser.add_argument("--provider", default="gemini_proxy",
                       help="LLM提供商 (默认: gemini_proxy)")
    parser.add_argument("--model", default="gemini-2.5-flash-preview-05-20",
                       help="模型名称")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--help-extended", action="store_true", help="显示扩展帮助")

    args = parser.parse_args()

    # 显示横幅
    print_banner()

    # 显示扩展帮助
    if args.help_extended:
        print_help()
        return

    # 创建Agent
    agent = create_agent_with_config(
        provider=args.provider,
        model=args.model,
        streaming=args.streaming
    )

    # 显示Agent信息
    if args.verbose:
        info = agent.get_agent_info()
        print(f"\n📊 Agent配置:")
        print(f"   框架: {info['framework']}")
        print(f"   工具: {info['tools_count']}个")
        print(f"   最大迭代: {info['max_iterations']}")
        print("─" * 60)

    try:
        # 根据参数选择运行模式
        if args.query:
            if args.batch:
                # 批处理模式 - 空格分割多个查询
                queries = args.query.split()
                run_batch_mode(agent, queries, args.streaming)
            else:
                # 单次查询模式
                print(f"\n📊 正在分析: {args.query}")
                print("─" * 60)

                if args.streaming:
                    result = asyncio.run(run_streaming_analysis(agent, args.query))
                else:
                    result = agent.analyze(args.query)

                print("\n📋 分析报告:")
                print("─" * 60)
                print(result)
        else:
            # 交互模式
            run_interactive_mode(agent, args.streaming)

    except KeyboardInterrupt:
        print("\n\n👋 程序被用户中断，再见！")
    except Exception as e:
        print(f"\n❌ 程序执行错误: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()