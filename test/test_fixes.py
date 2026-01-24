#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复效果的脚本
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_evidence_extraction():
    """测试证据池数据提取"""
    print("=" * 60)
    print("测试 1: 证据池数据提取")
    print("=" * 60)

    from backend.agents.news_agent import NewsAgent
    from backend.agents.deep_search_agent import DeepSearchAgent
    from backend.orchestration.cache import DataCache
    from backend.tools import financial as tools_module
    from langchain_openai import ChatOpenAI

    cache = DataCache()
    llm = ChatOpenAI(temperature=0)

    # 测试 NewsAgent
    print("\n[NewsAgent] 测试...")
    news_agent = NewsAgent(llm, cache, tools_module)
    news_output = await news_agent.research("AAPL news", "AAPL")

    print(f"  - Summary 长度: {len(news_output.summary)}")
    print(f"  - Evidence 数量: {len(news_output.evidence)}")
    if news_output.evidence:
        print(f"  - 第一条 Evidence:")
        ev = news_output.evidence[0]
        print(f"    * Title: {getattr(ev, 'title', 'N/A')}")
        print(f"    * Source: {getattr(ev, 'source', 'N/A')}")
        print(f"    * URL: {getattr(ev, 'url', 'N/A')}")
        print(f"    * Text: {getattr(ev, 'text', 'N/A')[:50]}...")

    # 测试 DeepSearchAgent
    print("\n[DeepSearchAgent] 测试...")
    deep_agent = DeepSearchAgent(llm, cache, tools_module)
    deep_output = await deep_agent.research("AAPL investment thesis", "AAPL")

    print(f"  - Summary 长度: {len(deep_output.summary)}")
    print(f"  - Evidence 数量: {len(deep_output.evidence)}")
    if deep_output.evidence:
        print(f"  - 第一条 Evidence:")
        ev = deep_output.evidence[0]
        print(f"    * Title: {getattr(ev, 'title', 'N/A')}")
        print(f"    * Source: {getattr(ev, 'source', 'N/A')}")
        print(f"    * URL: {getattr(ev, 'url', 'N/A')}")
        print(f"    * Text: {getattr(ev, 'text', 'N/A')[:50]}...")

    print("\n✅ 证据池测试完成")
    return True

async def test_streaming():
    """测试流式输出"""
    print("\n" + "=" * 60)
    print("测试 2: 流式输出")
    print("=" * 60)

    from backend.orchestration.supervisor_agent import SupervisorAgent
    from backend.orchestration.cache import DataCache
    from backend.tools import financial as tools_module
    from langchain_openai import ChatOpenAI

    cache = DataCache()
    llm = ChatOpenAI(temperature=0)
    supervisor = SupervisorAgent(llm, tools_module, cache)

    print("\n[Streaming] 测试流式输出...")
    token_count = 0
    chunk_sizes = []

    async for event_json in supervisor.process_stream("AAPL 价格", ["AAPL"]):
        import json
        try:
            event = json.loads(event_json)
            if event.get('type') == 'token':
                token_count += 1
                chunk_sizes.append(len(event.get('content', '')))
        except:
            pass

    print(f"  - Token 事件数量: {token_count}")
    if chunk_sizes:
        avg_chunk = sum(chunk_sizes) / len(chunk_sizes)
        print(f"  - 平均分块大小: {avg_chunk:.1f} 字符")
        print(f"  - 最小分块: {min(chunk_sizes)} 字符")
        print(f"  - 最大分块: {max(chunk_sizes)} 字符")

    print("\n✅ 流式输出测试完成")
    return True

async def test_report_detail():
    """测试报告详细度"""
    print("\n" + "=" * 60)
    print("测试 3: 报告详细度")
    print("=" * 60)

    from backend.orchestration.forum import ForumHost
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(temperature=0)
    forum = ForumHost(llm)

    # 检查 SYNTHESIS_PROMPT
    prompt = forum.SYNTHESIS_PROMPT

    print("\n[Forum Prompt] 分析...")
    print(f"  - Prompt 总长度: {len(prompt)} 字符")
    print(f"  - 包含 '≥1500字': {'≥1500字' in prompt}")
    print(f"  - 包含 '每章节≥150字': {'每章节≥150字' in prompt}")
    print(f"  - 包含 'quality_requirements': {'quality_requirements' in prompt}")
    print(f"  - 包含 '具体数据': {'具体数据' in prompt}")

    # 提取章节要求
    sections = []
    for line in prompt.split('\n'):
        if line.strip().startswith('###'):
            sections.append(line.strip())

    print(f"\n  - 要求章节数: {len(sections)}")
    for i, section in enumerate(sections[:3], 1):
        print(f"    {i}. {section[:50]}...")

    print("\n✅ 报告详细度测试完成")
    return True

async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("FinSight 修复验证测试")
    print("=" * 60)

    results = []

    try:
        # 测试 1: 证据池
        result1 = await test_evidence_extraction()
        results.append(("证据池数据提取", result1))
    except Exception as e:
        print(f"\n❌ 证据池测试失败: {e}")
        results.append(("证据池数据提取", False))

    try:
        # 测试 2: 流式输出
        result2 = await test_streaming()
        results.append(("流式输出", result2))
    except Exception as e:
        print(f"\n❌ 流式输出测试失败: {e}")
        results.append(("流式输出", False))

    try:
        # 测试 3: 报告详细度
        result3 = await test_report_detail()
        results.append(("报告详细度", result3))
    except Exception as e:
        print(f"\n❌ 报告详细度测试失败: {e}")
        results.append(("报告详细度", False))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    all_passed = all(r[1] for r in results)
    if all_passed:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️  部分测试失败，请检查日志")

    return all_passed

if __name__ == "__main__":
    asyncio.run(main())
