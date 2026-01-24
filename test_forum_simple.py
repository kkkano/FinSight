"""
简化的 Forum LLM 测试
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

async def test():
    print("=" * 60)
    print("Forum LLM 简化测试")
    print("=" * 60)

    # 1. 读取配置
    print("\n[1] 读取配置...")
    from backend.llm_config import get_llm_config
    config = get_llm_config()
    print(f"✅ 配置加载成功")
    print(f"   - Provider: {config.get('provider')}")
    print(f"   - Model: {config.get('model')}")
    print(f"   - API Base: {config.get('api_base')}")
    print(f"   - API Key: {config.get('api_key')[:10]}...")

    # 2. 初始化 LLM
    print("\n[2] 初始化 LLM...")
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config.get("api_base"),
        temperature=config.get("temperature", 0.3)
    )
    print(f"✅ LLM 初始化成功: {type(llm).__name__}")

    # 3. 测试简单调用
    print("\n[3] 测试简单 LLM 调用...")
    from langchain_core.messages import HumanMessage
    try:
        response = await llm.ainvoke([HumanMessage(content="Say 'OK'")])
        print(f"✅ LLM 调用成功")
        print(f"   - Response: {response.content}")
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. 测试 Forum
    print("\n[4] 测试 ForumHost...")
    from backend.orchestration.forum import ForumHost
    from backend.agents.base_agent import AgentOutput

    forum = ForumHost(llm)

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

    print("   调用 forum.synthesize()...")
    try:
        result = await forum.synthesize(mock_outputs)
        print(f"✅ Forum 调用成功")
        print(f"   - Consensus 长度: {len(result.consensus)} 字符")
        print(f"   - Confidence: {result.confidence}")
        print(f"   - Recommendation: {result.recommendation}")

        # 检查是否使用了 fallback
        if "### 1. 📊 执行摘要" in result.consensus and "HOLD (观望)" in result.consensus:
            print("\n⚠️  使用了 fallback_synthesis（LLM 调用失败）")
            print("\n前 500 字符:")
            print(result.consensus[:500])
        else:
            print("\n✅ 使用了 LLM 生成的报告")
            print("\n前 500 字符:")
            print(result.consensus[:500])

    except Exception as e:
        print(f"❌ Forum 调用失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test())
