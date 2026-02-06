# -*- coding: utf-8 -*-
"""
Phase 2 Demo Script
模拟完整调用流程，生成 Deep Research 报告并保存为 Markdown。
"""

import asyncio
import sys
import os
import json
from datetime import datetime

# Windows 终端编码修复
sys.stdout.reconfigure(encoding='utf-8')

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration.supervisor_agent import SupervisorAgent
from backend.services.memory import UserProfile
from backend.report.ir import ReportIR
from backend.report.validator import ReportValidator

# Mock LLM and Tools for Demo (to run without API keys if needed, but we'll try to use real logic where possible)
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base_agent import AgentOutput

class MockLLM:
    """模拟 LLM，用于生成合成文本"""
    async def ainvoke(self, prompt: str) -> str:
        prompt_str = str(prompt)
        if "consensus" in prompt_str.lower():
            # ForumHost synthesis response
            return """
            【共识观点】
            各方一致认为 NVDA 在 AI 芯片领域保持绝对领先地位，Hopper 系列需求强劲，Blackwell 爬坡顺利。数据中心业务是核心增长引擎。

            【分歧观点】
            部分观点担忧 2025 年下半年产能过剩风险，而另一派认为推理侧需求将接力训练侧，维持高景气度。

            【置信度】
            0.85

            【投资建议】
            BUY。考虑到用户为[进取型]，当前回调是布局良机。虽然短期波动可能加剧，但长期逻辑未变。

            【风险提示】
            1. 地缘政治风险（出口管制）
            2. 宏观经济衰退影响科技股估值
            3. 竞争对手（AMD, CSP 自研）份额蚕食
            """
        return "LLM Response Placeholder"

async def run_demo():
    print("🚀 开始 Phase 2 深度研报生成演示...")

    # 1. 初始化
    # 使用 Mock LLM 避免消耗 Token，且保证输出可控
    llm = MockLLM()
    # Mock Tools (实际环境会使用 backend.tools)
    tools = MagicMock()
    cache = MagicMock()

    supervisor = SupervisorAgent(llm, tools, cache)

    # 2. 模拟 DeepSearchAgent 和 MacroAgent 的真实返回 (因为 MockLLM 不会真去搜索)
    # 我们这里手动 patch 它们的 research 方法，让它们返回丰富的数据，模拟真实情况
    supervisor.agents["deep_search"].research = AsyncMock(return_value=AgentOutput(
        agent_name="deep_search",
        summary="检索到 3 篇深度研报。核心观点：Blackwell 芯片平均售价提升 40%，推高毛利。软件生态 CUDA 护城河依然稳固。",
        evidence=[
            {"text": "Blackwell 预计 2025 Q2 贡献显著营收", "source": "Morgan Stanley Report", "url": "http://example.com/ms"},
            {"text": "CSP 资本开支 2025 年预计增长 15%", "source": "Goldman Sachs", "url": "http://example.com/gs"}
        ],
        confidence=0.9,
        data_sources=["Deep Web"],
        as_of=datetime.now().isoformat()
    ))

    supervisor.agents["macro"].research = AsyncMock(return_value=AgentOutput(
        agent_name="macro",
        summary="美联储维持利率不变，但点阵图暗示年内降息 2 次。AI 泡沫论有所抬头，但基本面支撑依然强劲。",
        evidence=[
            {"text": "Fed Rate: 5.25-5.50%", "source": "FRED", "url": "https://fred.stlouisfed.org"},
            {"text": "US GDP Growth: 2.4%", "source": "BEA", "url": "https://bea.gov"}
        ],
        confidence=0.85,
        data_sources=["FRED"],
        as_of=datetime.now().isoformat()
    ))

    # 3. 准备用户画像 (Context Injection)
    user_profile = UserProfile(
        user_id="demo_user",
        risk_tolerance="high",       # 进取型
        investment_style="aggressive"
    )
    print(f"👤 用户画像: {user_profile.investment_style} / {user_profile.risk_tolerance}")

    # 4. 执行分析
    query = "分析 NVDA 的投资价值"
    ticker = "NVDA"
    print(f"🔍 分析目标: {ticker} - {query}")

    result = await supervisor.process(query, tickers=[ticker], user_profile=user_profile)

    # 5. 提取 ForumOutput 并转换为 ReportIR (模拟 ReportHandler 的工作)
    forum_output = result.forum_output

    # 手动构建 ReportIR (在实际 ReportHandler 中会有转换逻辑)
    # 这里为了演示效果，我们手动组装一个结构化非常好的对象
    report_ir_dict = {
        "report_id": "demo_report_001",
        "ticker": ticker,
        "company_name": "NVIDIA Corp",
        "title": f"{ticker} 深度投资价值分析",
        "summary": forum_output.consensus,
        "sentiment": "bullish",
        "confidence_score": forum_output.confidence,
        "sections": [
            {
                "title": "核心观点 (Executive Summary)",
                "order": 1,
                "contents": [
                    {"type": "text", "content": forum_output.consensus}
                ]
            },
            {
                "title": "宏观与行业环境",
                "order": 2,
                "contents": [
                    {"type": "text", "content": "宏观环境显示软着陆可能性大，利好成长股。"},
                    {"type": "chart", "content": {"type": "line", "data": "fred_rate_chart"}, "metadata": {"title": "美联储利率走势"}}
                ]
            },
            {
                "title": "深度基本面分析",
                "order": 3,
                "contents": [
                    {"type": "text", "content": "Blackwell 架构带来的 ASP 提升是关键驱动力。"},
                    {"type": "table", "content": {"headers": ["Year", "Revenue"], "rows": [["2024", "60B"], ["2025", "100B"]]}}
                ]
            },
            {
                "title": "投资建议与风险",
                "order": 4,
                "contents": [
                    {"type": "text", "content": f"建议：{forum_output.recommendation}。{forum_output.risks[0]}"}
                ]
            }
        ],
        "citations": [
            {"source_id": "1", "title": "Morgan Stanley Report", "url": "http://example.com/ms", "snippet": "Blackwell...", "published_date": "2024-12-01"}
        ]
    }

    # 6. 校验 IR
    validated_report = ReportValidator.validate_and_fix(report_ir_dict)
    print("✅ ReportIR 校验通过")

    # 7. 渲染为 Markdown
    md_content = render_markdown(validated_report)

    # 8. 保存文件
    output_path = "docs/reports/PHASE2_DEMO_REPORT.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"📄 报告已生成: {output_path}")

def render_markdown(report: ReportIR) -> str:
    """将 ReportIR 渲染为 Markdown (模拟前端展示)"""
    lines = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(f"**Ticker**: {report.ticker} | **Date**: {report.generated_at[:10]}")
    lines.append(f"**Sentiment**: {report.sentiment.value.upper()} | **Confidence**: {report.confidence_score*100}%")
    lines.append("")
    lines.append("## 摘要")
    lines.append(report.summary.strip())
    lines.append("")

    for section in report.sections:
        lines.append(f"## {section.title}")
        for content in section.contents:
            if content.type == "text":
                lines.append(str(content.content))
                lines.append("")
            elif content.type == "chart":
                lines.append(f"*[Chart: {content.metadata.get('title', 'Untitled')}]*")
                lines.append("")
            elif content.type == "table":
                lines.append("*[Table Data]*")
                lines.append("")

    lines.append("## 引用来源")
    for cit in report.citations:
        lines.append(f"- [{cit.title}]({cit.url}): {cit.snippet}")

    return os.linesep.join(lines)

if __name__ == "__main__":
    asyncio.run(run_demo())
