#!/usr/bin/env python
"""
快速测试脚本 - 验证系统功能
"""

from backend.langchain_agent import create_financial_agent

def test_agent_creation():
    """测试 Agent 创建"""
    print("🔧 测试 Agent 创建...")
    try:
        agent = create_financial_agent(
            provider="gemini_proxy",
            model="gemini-2.5-flash-preview-05-20",
            verbose=False,
            max_iterations=5
        )
        print("✅ Agent 创建成功")
        return agent
    except Exception as e:
        print(f"❌ Agent 创建失败: {e}")
        return None

def test_simple_query(agent):
    """测试简单查询"""
    print("\n📊 测试简单查询...")
    try:
        result = agent.analyze("获取当前时间")
        print(f"✅ 查询成功")
        print(f"📝 结果长度: {len(result)} 字符")
        if len(result) > 200:
            print(f"📄 结果预览: {result[:200]}...")
        else:
            print(f"📄 结果: {result}")
        return True
    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*60)
    print("🎯 FinSight 快速功能测试")
    print("="*60)
    
    # 测试1: Agent 创建
    agent = test_agent_creation()
    if not agent:
        print("\n❌ 测试失败：无法创建 Agent")
        return
    
    # 测试2: 简单查询
    success = test_simple_query(agent)
    
    # 总结
    print("\n" + "="*60)
    if success:
        print("✅ 所有测试通过！系统运行正常")
    else:
        print("⚠️ 部分测试失败")
    print("="*60)

if __name__ == "__main__":
    main()
