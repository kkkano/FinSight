"""
LLM 适配器 - 实现 LLMPort

使用 LiteLLM 进行意图分类和报告生成。
"""

import json
import re
from typing import Dict, Any, Optional

from finsight.domain.models import (
    Intent,
    RouteDecision,
    ClarifyQuestion,
)
from finsight.ports.interfaces import (
    LLMPort,
    DataUnavailableError,
)


# 尝试导入 litellm
try:
    from litellm import completion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    completion = None


class LiteLLMAdapter(LLMPort):
    """
    LiteLLM 适配器

    实现 LLMPort 接口，提供意图分类和报告生成功能。
    """

    # 意图分类提示词
    INTENT_CLASSIFICATION_PROMPT = """你是一个金融查询意图分类器。分析用户的查询并返回 JSON 格式的结果。

可用的意图类型：
- stock_analysis: 深度股票分析（如"分析特斯拉"、"TSLA 投资分析"）
- stock_price: 股票价格查询（如"特斯拉股价"、"AAPL 现在多少钱"）
- stock_news: 股票新闻（如"特斯拉最新消息"、"苹果新闻"）
- company_info: 公司信息（如"特斯拉是做什么的"、"苹果公司介绍"）
- compare_assets: 资产对比（如"对比特斯拉和比亚迪"、"黄金和比特币哪个好"）
- market_sentiment: 市场情绪（如"市场恐惧指数"、"现在市场情绪如何"）
- macro_events: 宏观经济事件（如"本月有什么经济数据"、"FOMC 会议时间"）
- historical_analysis: 历史回撤分析（如"纳斯达克历史回撤"、"大盘历史最大跌幅"）
- general_search: 通用搜索（无法归类到上述类别）
- unclear: 意图不明确，需要追问

用户查询: {query}

返回 JSON 格式（不要包含 markdown 代码块）：
{{
    "intent": "意图类型",
    "confidence": 0.0-1.0 的置信度,
    "ticker": "提取的股票代码（如有）",
    "tickers": ["多个股票代码列表（如对比场景）"],
    "missing_fields": ["缺失的必要信息"],
    "clarify_question": "如需追问，这里是追问的问题"
}}"""

    # 报告生成提示词（Summary 模式）
    SUMMARY_REPORT_PROMPT = """根据以下数据生成一份简洁的投资分析摘要（300-500字）。

数据：
{data}

要求：
1. 使用 Markdown 格式
2. 包含：当前状态、3个关键要点、投资建议（BUY/HOLD/SELL）、主要风险
3. 语言简洁专业
4. 所有数据必须标注来源和时间"""

    # 报告生成提示词（Deep 模式）
    DEEP_REPORT_PROMPT = """根据以下数据生成一份专业的投资分析报告（800字以上）。

数据：
{data}

要求：
1. 使用 Markdown 格式
2. 包含章节：执行摘要、当前市场状况、基本面分析、技术面分析、风险评估、投资建议
3. 给出明确的 BUY/HOLD/SELL 建议及目标价位
4. 包含牛市/熊市/基准情景分析
5. 所有数据必须标注来源和时间
6. 专业、详细、可操作"""

    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: str = "gemini-2.5-flash-preview-05-20",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        """
        初始化适配器

        Args:
            provider: LLM 提供商
            model: 模型名称
            api_key: API 密钥（可选）
            api_base: API 基础 URL（可选）
        """
        if not LITELLM_AVAILABLE:
            raise ImportError("litellm 未安装，请运行: pip install litellm")

        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.api_base = api_base

    def _call_llm(self, messages: list, temperature: float = 0.3) -> str:
        """调用 LLM"""
        try:
            response = completion(
                model=f"{self.provider}/{self.model}" if self.provider else self.model,
                messages=messages,
                temperature=temperature,
                api_key=self.api_key,
                api_base=self.api_base,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise DataUnavailableError(
                f"LLM 调用失败: {str(e)}",
                source=f"{self.provider}/{self.model}"
            )

    def classify_intent(
        self,
        query: str,
        context: Optional[str] = None
    ) -> RouteDecision:
        """分类用户意图"""
        prompt = self.INTENT_CLASSIFICATION_PROMPT.format(query=query)

        if context:
            prompt += f"\n\n上下文信息：{context}"

        messages = [{"role": "user", "content": prompt}]

        try:
            response = self._call_llm(messages, temperature=0.1)

            # 尝试解析 JSON
            # 移除可能的 markdown 代码块标记
            response = re.sub(r'```json\s*', '', response)
            response = re.sub(r'```\s*', '', response)

            result = json.loads(response.strip())

            intent_str = result.get('intent', 'unclear')
            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.UNCLEAR

            confidence = float(result.get('confidence', 0.5))
            missing_fields = result.get('missing_fields', [])

            clarify_question = None
            if result.get('clarify_question') or intent == Intent.UNCLEAR:
                clarify_question = ClarifyQuestion(
                    question=result.get('clarify_question', '请提供更多信息'),
                    options=None,
                    field_name=missing_fields[0] if missing_fields else 'unknown',
                    reason='意图不明确' if intent == Intent.UNCLEAR else '缺少必要信息',
                )

            extracted_params = {}
            if result.get('ticker'):
                extracted_params['ticker'] = result['ticker'].upper()
            if result.get('tickers'):
                extracted_params['tickers'] = [t.upper() for t in result['tickers']]

            return RouteDecision(
                intent=intent,
                confidence=confidence,
                extracted_params=extracted_params,
                missing_fields=missing_fields,
                needs_clarification=confidence < 0.7 or bool(missing_fields),
                clarify_question=clarify_question,
            )

        except json.JSONDecodeError:
            # JSON 解析失败，返回 unclear
            return RouteDecision(
                intent=Intent.UNCLEAR,
                confidence=0.3,
                extracted_params={},
                missing_fields=[],
                needs_clarification=True,
                clarify_question=ClarifyQuestion(
                    question="抱歉，我没能理解您的问题。请问您想查询什么？",
                    options=["股票分析", "股票价格", "市场情绪", "经济日历"],
                    field_name='intent',
                    reason='意图解析失败',
                ),
            )

    def generate_report(
        self,
        data: Dict[str, Any],
        template: str,
        mode: str = "deep"
    ) -> str:
        """生成分析报告"""
        if mode == "summary":
            prompt = self.SUMMARY_REPORT_PROMPT.format(data=json.dumps(data, ensure_ascii=False, indent=2))
        else:
            prompt = self.DEEP_REPORT_PROMPT.format(data=json.dumps(data, ensure_ascii=False, indent=2))

        messages = [{"role": "user", "content": prompt}]

        return self._call_llm(messages, temperature=0.5)

    def extract_entities(self, query: str) -> Dict[str, Any]:
        """从查询中提取实体"""
        prompt = f"""从以下查询中提取金融相关实体，返回 JSON 格式：

查询: {query}

提取：
- tickers: 股票代码列表
- companies: 公司名称列表
- time_range: 时间范围（如"最近一周"、"2024年"）
- metrics: 指标类型（如"价格"、"市盈率"）

返回 JSON（不要包含 markdown 代码块）："""

        messages = [{"role": "user", "content": prompt}]

        try:
            response = self._call_llm(messages, temperature=0.1)
            response = re.sub(r'```json\s*', '', response)
            response = re.sub(r'```\s*', '', response)
            return json.loads(response.strip())
        except:
            return {"tickers": [], "companies": [], "time_range": None, "metrics": []}
