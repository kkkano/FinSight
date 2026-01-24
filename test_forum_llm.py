"""
测试 Forum LLM 调用
用于诊断 Forum 合成报告时 LLM 调用失败的问题
"""
import asyncio
import logging
import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def test_forum_llm():
    """测试 Forum 的 LLM 调用"""
    print("=" * 60)
    print("Forum LLM 调用诊断测试")
    print("=" * 60)

    # 1. 检查环境变量
    print("\n[1] 检查环境变量...")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ 未找到 API Key (OPENAI_API_KEY 或 ANTHROPIC_API_KEY)")
        return
    print(f"✅ API Key 已配置: {api_key[:10]}...")

    # 2. 初始化 LLM
    print("\n[2] 初始化 LLM...")
    try:
        # 直接使用 llm_config 初始化 LLM
        from backend.llm_config import create_llm
        llm = create_llm()

        print(f"✅ LLM 初始化成功: {type(llm).__name__}")
        print(f"   - 类型: {type(llm)}")
        print(f"   - 是否有 ainvoke: {hasattr(llm, 'ainvoke')}")
    except Exception as e:
        print(f"❌ LLM 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. 测试简单的 LLM 调用
    print("\n[3] 测试简单的 LLM 调用...")
    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content="Hello, respond with 'OK'")])
        print(f"✅ LLM 调用成功")
        print(f"   - Response 类型: {type(response)}")
        print(f"   - 是否有 content: {hasattr(response, 'content')}")
        if hasattr(response, 'content'):
            print(f"   - Content: {response.content[:100]}")
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. 测试 Forum 初始化
    print("\n[4] 测试 ForumHost 初始化...")
    try:
        from backend.orchestration.forum import ForumHost
        forum = ForumHost(llm)
        print(f"✅ ForumHost 初始化成功")
        print(f"   - forum.llm 类型: {type(forum.llm).__name__}")
        print(f"   - forum.llm 是否为 None: {forum.llm is None}")
    except Exception as e:
        print(f"❌ ForumHost 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 5. 测试 Prompt 格式化
    print("\n[5] 测试 FORUM_SYNTHESIS_PROMPT 格式化...")
    try:
        from backend.prompts.system_prompts import FORUM_SYNTHESIS_PROMPT

        # 准备测试数据
        context_parts = {
            "price": "测试价格数据",
            "news": "测试新闻数据",
            "technical": "测试技术分析",
            "fundamental": "测试基本面",
            "deep_search": "测试深度搜索",
            "macro": "测试宏观数据"
        }

        prompt = FORUM_SYNTHESIS_PROMPT.format(
            risk_tolerance="medium",
            investment_style="balanced",
            user_instruction="",
            context_info="测试上下文",
            conflict_notes="无冲突",
            **context_parts
        )

        print(f"✅ Prompt 格式化成功")
        print(f"   - Prompt 长度: {len(prompt)} 字符")
        print(f"   - Prompt 前 200 字符: {prompt[:200]}")
    except Exception as e:
        print(f"❌ Prompt 格式化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 6. 测试完整的 Forum synthesize 调用
    print("\n[6] 测试 Forum.synthesize() 调用...")
    try:
        from backend.agents.base_agent import AgentOutput

        # 构造模拟的 Agent 输出
        mock_outputs = {
            "price": AgentOutput(
                agent_name="price",
                summary="AAPL 当前价格 $150.00，上涨 2.5%",
                confidence=0.9,
                evidence=[],
                data_sources=["mock"],
                as_of="2024-01-24"
            ),
            "news": AgentOutput(
                agent_name="news",
                summary="苹果发布新产品，市场反应积极",
                confidence=0.8,
                evidence=[],
                data_sources=["mock"],
                as_of="2024-01-24"
            )
        }

        result = await forum.synthesize(mock_outputs, user_profile=None, context_summary="测试上下文")

        print(f"✅ Forum.synthesize() 调用成功")
        print(f"   - Consensus 长度: {len(result.consensus)} 字符")
        print(f"   - Confidence: {result.confidence}")
        print(f"   - Recommendation: {result.recommendation}")
        print(f"   - Consensus 前 500 字符:\n{result.consensus[:500]}")

        # 检查是否使用了 fallback
        if "### 1. 📊 执行摘要" in result.consensus and "HOLD (观望)" in result.consensus:
            print("\n⚠️  警告: 使用了 fallback_synthesis，LLM 调用可能失败了")
        else:
            print("\n✅ 使用了 LLM 生成的报告（非 fallback）")

    except Exception as e:
        print(f"❌ Forum.synthesize() 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_forum_llm())
