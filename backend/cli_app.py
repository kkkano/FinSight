#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinSight AI 金融分析主程序
支持两种模式：
1. 对话模式 (默认): 使用 ConversationAgent 进行多轮对话
2. 报告模式: 使用原有 LangChain Agent 生成深度报告

LangChain 1.0.1 驱动 | 实时流式分析 | 专业投资报告
"""

import sys
import os
import argparse
from typing import Optional
from datetime import datetime

# 设置 UTF-8 编码
if sys.platform.startswith('win'):
    import codecs
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 导入组件
try:
    from langchain_agent import create_financial_agent, LangChainFinancialAgent
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    LangChainFinancialAgent = None

try:
    from backend.conversation.agent import ConversationAgent
    from backend.orchestration.orchestrator import ToolOrchestrator
    from backend.orchestration.tools_bridge import register_all_financial_tools
    CONVERSATION_AVAILABLE = True
except ImportError as e:
    print(f"警告: 对话模块未找到 - {e}")
    CONVERSATION_AVAILABLE = False
    ConversationAgent = None

# LangSmith 可观测性（可选）
try:
    from langsmith_integration import quick_init as init_langsmith, get_status as langsmith_status
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    init_langsmith = lambda: False
    langsmith_status = lambda: {"enabled": False}


# === 界面函数 ===

def print_banner(mode: str = "conversation"):
    """打印程序横幅"""
    print("=" * 70)
    print("🔍 FinSight AI - 智能金融分析系统")
    print(f"📊 模式: {'对话式分析' if mode == 'conversation' else '深度报告生成'}")
    print(f"🕐 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if LANGSMITH_AVAILABLE:
        init_langsmith()
        status = langsmith_status()
        if status.get("enabled"):
            print(f"🔭 LangSmith: 已启用")
    
    print("=" * 70)


def print_conversation_help():
    """打印对话模式帮助"""
    print("""
💡 对话模式使用指南
──────────────────────────────────────
📌 快速查询示例:
   • "AAPL 现在多少钱"
   • "苹果公司最新新闻"
   • "特斯拉今天涨了吗"

📊 深度分析示例:
   • "分析 NVDA 股票"
   • "帮我分析一下特斯拉值不值得买"
   • "详细分析苹果公司的投资价值"

🔔 监控提醒 (开发中):
   • "帮我盯着 TSLA，跌到 200 提醒我"

🔄 追问示例:
   • "为什么呢"
   • "风险在哪"
   • "详细说说"

⚙️ 命令:
   • help  - 显示此帮助
   • stats - 显示对话统计
   • clear - 清空对话历史
   • exit  - 退出程序
──────────────────────────────────────
""")


def print_stats(agent: ConversationAgent):
    """打印统计信息"""
    stats = agent.get_stats()
    print(f"""
📊 对话统计
──────────────────────────────────────
  总查询数: {stats['total_queries']}
  当前焦点: {stats.get('current_focus', '无')}
  对话轮数: {stats.get('context_turns', 0)}
  会话时长: {stats.get('session_duration_seconds', 0):.0f} 秒

意图分布:
  💬 快速对话: {stats['intents'].get('chat', 0)}
  📊 深度报告: {stats['intents'].get('report', 0)}
  🔔 监控提醒: {stats['intents'].get('alert', 0)}
  🔄 追问: {stats['intents'].get('followup', 0)}
  ❓ 需澄清: {stats['intents'].get('clarify', 0)}
  ❌ 错误数: {stats.get('errors', 0)}
──────────────────────────────────────
""")


# === 对话模式 ===

def run_conversation_mode(use_orchestrator: bool = True):
    """运行对话模式"""
    if not CONVERSATION_AVAILABLE:
        print("❌ 对话模块不可用，请检查 backend 模块")
        return
    
    print_banner("conversation")
    print_conversation_help()
    
    # 初始化 Orchestrator
    orchestrator = None
    if use_orchestrator:
        try:
            orchestrator = ToolOrchestrator()
            register_all_financial_tools(orchestrator)
            print("✅ 数据源编排器已初始化\n")
        except Exception as e:
            print(f"⚠️ 编排器初始化失败: {e}\n")
    
    # 创建对话 Agent
    agent = ConversationAgent(orchestrator=orchestrator)
    
    print("🎯 准备就绪！请输入您的问题：\n")
    
    while True:
        try:
            # 显示当前焦点
            focus = agent.context.current_focus
            if focus:
                prompt = f"[{focus}] 🔍 "
            else:
                prompt = "🔍 "
            
            query = input(prompt).strip()
            
            if not query:
                continue
            
            # 处理命令
            query_lower = query.lower()
            
            if query_lower in ['exit', 'quit', '退出', 'q']:
                print("\n👋 感谢使用 FinSight AI，祝您投资顺利！")
                print_stats(agent)
                break
            
            if query_lower in ['help', '帮助', 'h', '?']:
                print_conversation_help()
                continue
            
            if query_lower in ['stats', '统计']:
                print_stats(agent)
                continue
            
            if query_lower in ['clear', '清空']:
                agent.reset()
                print("✅ 对话历史已清空\n")
                continue
            
            # 处理查询
            print()  # 空行
            
            try:
                result = agent.chat(query)
                
                # 显示响应
                response = result.get('response', '无响应')
                intent = result.get('intent', 'unknown')
                response_time = result.get('response_time_ms', 0)
                
                # 意图图标
                intent_icons = {
                    'chat': '💬',
                    'report': '📊',
                    'alert': '🔔',
                    'followup': '🔄',
                    'clarify': '❓',
                }
                icon = intent_icons.get(intent, '💡')
                
                print(f"{icon} [{intent}] ({response_time:.0f}ms)")
                print("─" * 50)
                print(response)
                print("─" * 50)
                print()
                
            except Exception as e:
                print(f"❌ 处理失败: {str(e)}\n")
        
        except KeyboardInterrupt:
            print("\n\n👋 程序被中断，再见！")
            break
        except EOFError:
            print("\n👋 再见！")
            break


# === 报告模式 (原有功能) ===

def run_report_mode(query: str, provider: str = "gemini_proxy", 
                    model: str = "gemini-2.5-flash"):
    """运行报告生成模式"""
    if not LANGCHAIN_AVAILABLE:
        print("❌ LangChain Agent 不可用")
        return
    
    print_banner("report")
    
    try:
        agent = create_financial_agent(
            provider=provider,
            model=model,
            verbose=True,
            max_iterations=15
        )
        print(f"✅ Agent 创建成功 | 提供商: {provider}\n")
        
        print(f"📊 正在分析: {query}")
        print("─" * 60)
        
        result = agent.analyze(query)
        
        print("\n📋 分析报告:")
        print("─" * 60)
        print(result)
        
    except Exception as e:
        print(f"❌ 分析失败: {str(e)}")


def run_interactive_report_mode(provider: str = "gemini_proxy",
                                 model: str = "gemini-2.5-flash"):
    """运行交互式报告模式"""
    if not LANGCHAIN_AVAILABLE:
        print("❌ LangChain Agent 不可用")
        return
    
    print_banner("report")
    
    try:
        agent = create_financial_agent(
            provider=provider,
            model=model,
            verbose=True,
            max_iterations=15
        )
        print(f"✅ Agent 创建成功\n")
        
        print("🎯 深度报告模式 - 输入 'exit' 退出\n")
        
        while True:
            try:
                query = input("🔍 请输入分析目标: ").strip()
                
                if query.lower() in ['exit', 'quit', '退出', 'q']:
                    print("\n👋 再见！")
                    break
                
                if not query:
                    continue
                
                print(f"\n📊 正在生成报告: {query}")
                print("─" * 60)
                
                result = agent.analyze(query)
                
                print("\n📋 分析报告:")
                print("─" * 60)
                print(result)
                print()
                
            except KeyboardInterrupt:
                print("\n\n👋 程序被中断")
                break
                
    except Exception as e:
        print(f"❌ Agent 创建失败: {str(e)}")


# === 主函数 ===

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="FinSight AI - 智能金融分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                        # 对话模式 (默认)
  python main.py --report               # 交互式报告模式
  python main.py "分析AAPL" --report    # 单次报告生成
  python main.py --help                 # 显示帮助
        """
    )
    
    parser.add_argument("query", nargs="?", help="分析查询 (仅报告模式)")
    parser.add_argument("--report", "-r", action="store_true", 
                       help="使用报告生成模式 (原有功能)")
    parser.add_argument("--no-orchestrator", action="store_true",
                       help="禁用数据源编排器")
    parser.add_argument("--provider", default="gemini_proxy",
                       help="LLM 提供商 (报告模式)")
    parser.add_argument("--model", default="gemini-2.5-flash",
                       help="模型名称 (报告模式)")
    
    args = parser.parse_args()
    
    try:
        if args.report:
            # 报告模式
            if args.query:
                run_report_mode(args.query, args.provider, args.model)
            else:
                run_interactive_report_mode(args.provider, args.model)
        else:
            # 对话模式 (默认)
            run_conversation_mode(use_orchestrator=not args.no_orchestrator)
    
    except KeyboardInterrupt:
        print("\n\n👋 程序被中断，再见！")
    except Exception as e:
        print(f"\n❌ 程序错误: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
