# -*- coding: utf-8 -*-
"""
FollowupHandler - 追问处理器
处理基于上下文的追问
"""

import sys
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import re

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class FollowupHandler:
    """
    追问处理器
    
    用于处理：
    - "为什么？"
    - "详细说说"
    - "风险呢？"
    等基于上下文的追问
    
    关键：必须有上下文才能正确处理追问
    """
    
    # 追问类型映射
    FOLLOWUP_TYPES = {
        'why': ['为什么', 'why', '原因', 'reason', '怎么会'],
        'detail': ['详细', '具体', 'detail', 'more', '展开', '深入', '解释'],
        'risk': ['风险', 'risk', '危险', '隐患', '问题', '缺点', '不好'],
        'advantage': ['优势', '优点', '好处', 'advantage', 'benefit', '利好'],
        'comparison': ['对比', '比较', 'compare', 'vs', '相比', '区别'],
        'prediction': ['预测', '未来', 'forecast', 'predict', '走势', '趋势'],
        'strategy': ['怎么办', '策略', 'strategy', '建议', '操作', '应该'],
    }
    
    def __init__(self, llm=None, orchestrator=None):
        """
        初始化处理器
        
        Args:
            llm: LLM 实例
            orchestrator: ToolOrchestrator 实例
        """
        self.llm = llm
        self.orchestrator = orchestrator
        self._init_tools()
    
    def _init_tools(self):
        """初始化工具函数"""
        # 优先从 orchestrator 获取 tools_module
        if self.orchestrator and self.orchestrator.tools_module:
            self.tools_module = self.orchestrator.tools_module
            return
        
        # 回退：直接导入
        try:
            from backend import tools
            self.tools_module = tools
        except ImportError:
            try:
                import tools
                self.tools_module = tools
            except ImportError:
                self.tools_module = None
    
    def handle(
        self, 
        query: str, 
        metadata: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        处理追问
        
        Args:
            query: 用户追问
            metadata: 提取的元数据
            context: 对话上下文（关键！）
            
        Returns:
            响应字典
        """
        # 检查上下文
        if not context or not context.history:
            return {
                'success': True,
                'response': self._no_context_response(),
                'needs_clarification': True,
                'intent': 'followup',
            }
        
        # 获取追问类型
        followup_type = self._classify_followup(query)
        
        # 获取上下文信息
        last_response = context.get_last_response()
        last_long_response = getattr(context, "get_last_long_response", lambda: None)()
        current_focus = context.current_focus
        cached_data = context.get_all_cached_data()

        # 如果有最近长文本（报告），根据用户动作直接做翻译/摘要/结论/风险
        if last_long_response:
            action = self._detect_report_action(query.lower())
            return self._handle_report_followup(action, last_long_response)
        
        # 根据追问类型处理
        if self.llm:
            return self._handle_with_llm(
                query=query,
                followup_type=followup_type,
                last_response=last_response,
                current_focus=current_focus,
                cached_data=cached_data,
                context=context
            )
        else:
            return self._handle_without_llm(
                query=query,
                followup_type=followup_type,
                last_response=last_response,
                current_focus=current_focus,
                cached_data=cached_data
            )
    
    def _classify_followup(self, query: str) -> str:
        """分类追问类型"""
        query_lower = query.lower()
        
        for ftype, keywords in self.FOLLOWUP_TYPES.items():
            if any(kw in query_lower for kw in keywords):
                return ftype
        
        return 'general'  # 通用追问
    
    def _handle_with_llm(
        self,
        query: str,
        followup_type: str,
        last_response: Optional[str],
        current_focus: Optional[str],
        cached_data: Dict[str, Any],
        context: Any
    ) -> Dict[str, Any]:
        """使用 LLM 处理追问"""
        from langchain_core.messages import HumanMessage
        from backend.prompts.system_prompts import FOLLOWUP_SYSTEM_PROMPT
        
        # 获取对话历史
        conversation_history = self._format_conversation_history(context)
        
        # 格式化缓存数据
        previous_data = self._format_cached_data(cached_data)
        
        prompt = FOLLOWUP_SYSTEM_PROMPT.format(
            conversation_history=conversation_history,
            current_focus=current_focus or "No specific focus",
            previous_data=previous_data,
            query=query
        )
        
        # Add specific guidance based on follow-up type
        type_guidance = self._get_type_guidance(followup_type)
        prompt += f"\n\nSpecific Guidance: {type_guidance}"
        
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            
            return {
                'success': True,
                'response': response.content,
                'intent': 'followup',
                'followup_type': followup_type,
                'current_focus': current_focus,
            }
        
        except Exception as e:
            return {
                'success': False,
                'response': f"处理追问时出错: {str(e)}",
                'error': str(e),
                'intent': 'followup',
            }
    
    def _handle_without_llm(
        self,
        query: str,
        followup_type: str,
        last_response: Optional[str],
        current_focus: Optional[str],
        cached_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """不使用 LLM 处理追问（简化版）"""
        
        # 根据追问类型生成响应
        if followup_type == 'why':
            response = self._generate_why_response(current_focus, cached_data)
        elif followup_type == 'risk':
            response = self._generate_risk_response(current_focus, cached_data)
        elif followup_type == 'advantage':
            response = self._generate_advantage_response(current_focus, cached_data)
        elif followup_type == 'detail':
            response = self._generate_detail_response(current_focus, cached_data, last_response)
        else:
            response = self._generate_general_response(current_focus, cached_data)
        
        return {
            'success': True,
            'response': response,
            'intent': 'followup',
            'followup_type': followup_type,
            'current_focus': current_focus,
        }
    
    def _format_conversation_history(self, context: Any) -> str:
        """格式化对话历史"""
        if not context or not context.history:
            return "无历史对话"
        
        lines = []
        for turn in list(context.history)[-5:]:
            lines.append(f"用户: {turn.query}")
            if turn.response:
                # 截取响应的前 200 字符
                resp = turn.response[:200] + "..." if len(turn.response) > 200 else turn.response
                lines.append(f"助手: {resp}")
        
        return "\n".join(lines)
    
    def _format_cached_data(self, cached_data: Dict[str, Any]) -> str:
        """格式化缓存数据"""
        if not cached_data:
            return "无缓存数据"
        
        lines = []
        for key, value in cached_data.items():
            # 截取每个值的前 100 字符
            value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            lines.append(f"- {key}: {value_str}")
        
        return "\n".join(lines)
    
    def _get_type_guidance(self, followup_type: str) -> str:
        """Get specific guidance for follow-up type"""
        guidance = {
            'why': "Please explain the reasons and logic behind the previous statement",
            'detail': "Please elaborate on the previous analysis in detail, providing more specifics",
            'risk': "Please focus on analyzing potential risks and negative factors",
            'advantage': "Please focus on analyzing advantages and positive factors",
            'comparison': "Please conduct a comparative analysis with related assets",
            'prediction': "Please analyze possible future trends and movements",
            'strategy': "Please provide specific investment strategy recommendations",
            'general': "Please answer the user's question based on the context",
        }
        return guidance.get(followup_type, guidance['general'])
    
    def _generate_why_response(self, focus: Optional[str], data: Dict) -> str:
        """生成"为什么"类追问的响应"""
        if not focus:
            return "请先告诉我您想了解哪支股票的分析原因。"
        
        return f"""关于 {focus} 的分析原因：

这个判断主要基于以下几个方面：
1. 当前的市场状况和价格走势
2. 公司的基本面情况
3. 行业整体环境
4. 市场情绪指标

如果您想了解更具体的某个方面，请告诉我。"""
    
    def _generate_risk_response(self, focus: Optional[str], data: Dict) -> str:
        """生成风险类追问的响应"""
        if not focus:
            return "请先告诉我您想了解哪支股票的风险分析。"
        
        return f"""关于 {focus} 的主要风险因素：

1. **市场风险**: 整体市场下跌可能带动股价下行
2. **行业风险**: 行业竞争加剧或政策变化的影响
3. **公司特有风险**: 业绩不达预期、管理层变动等
4. **估值风险**: 当前估值水平是否合理

建议在投资前设定明确的止损位，控制单只股票的仓位。

需要我详细分析某个具体风险吗？"""
    
    def _generate_advantage_response(self, focus: Optional[str], data: Dict) -> str:
        """生成优势类追问的响应"""
        if not focus:
            return "请先告诉我您想了解哪支股票的优势分析。"
        
        return f"""关于 {focus} 的主要优势：

需要结合最新的公司数据来分析具体优势。通常包括：
1. 市场地位和竞争优势
2. 财务健康状况
3. 增长潜力
4. 管理团队能力

您想让我获取最新数据来分析吗？"""
    
    def _generate_detail_response(
        self, 
        focus: Optional[str], 
        data: Dict,
        last_response: Optional[str]
    ) -> str:
        """生成详细解释的响应"""
        if last_response:
            return f"""基于之前的分析，让我进一步展开：

{last_response[:500] if len(last_response) > 500 else last_response}

如果您想了解某个特定方面的更多细节，请告诉我：
- 财务数据详情
- 技术分析
- 行业对比
- 近期催化剂"""
        
        return "请告诉我您想了解哪方面的详细信息。"
    
    def _generate_general_response(self, focus: Optional[str], data: Dict) -> str:
        """生成通用追问的响应"""
        if focus:
            return f"""关于 {focus}：

我可以为您提供以下方面的信息：
1. 实时价格和走势
2. 公司基本面分析
3. 最新新闻和动态
4. 投资建议

请告诉我您最想了解哪个方面？"""
        
        return """请问您想了解什么？

我可以帮您：
- 查询股票价格
- 分析投资机会
- 解读市场动态
- 设置价格提醒

请具体告诉我您的需求。"""

    # === 报告跟进：翻译/摘要/结论/风险等 ===
    def _detect_report_action(self, query_lower: str) -> str:
        if '翻译' in query_lower or 'translate' in query_lower:
            if '英文' in query_lower or 'english' in query_lower:
                return 'translate_en'
            return 'translate_zh'
        if any(k in query_lower for k in ['总结', '概要', '摘要', '要点', 'key takeaways', 'summary']):
            return 'summary'
        if any(k in query_lower for k in ['结论', 'recommendation', 'call']):
            return 'conclusion'
        if '风险' in query_lower or 'risk' in query_lower:
            return 'risk'
        return 'summary'

    def _handle_report_followup(self, action: str, text: str) -> Dict[str, Any]:
        """
        基于最近报告文本做翻译/摘要/结论/风险提炼。
        无 LLM 时截取片段并声明来源，避免“当成新对话”。
        """
        prefix = f"基于最近报告片段（长度约 {len(text)} 字），以下内容为自动生成，供参考：\n"
        paragraphs = [p.strip() for p in text.split('\\n') if p.strip()]
        head = '\\n'.join(paragraphs[:6]) if paragraphs else text[:800]

        if action == 'translate_en':
            resp = prefix + head
        elif action == 'translate_zh':
            resp = prefix + head
        elif action == 'conclusion':
            resp = prefix + "结论/要点提炼：\n" + head
        elif action == 'risk':
            resp = prefix + "风险要点提炼：\n" + head
        else:
            resp = prefix + "摘要：\n" + head

        return {
            'success': True,
            'response': resp,
            'intent': 'followup',
            'followup_type': action,
        }
    
    def _no_context_response(self) -> str:
        """没有上下文时的响应"""
        return """抱歉，我不太确定您在追问什么。

这可能是因为：
1. 这是一个新的对话，没有之前的分析内容
2. 您的问题需要更多上下文

请您：
- 先提出一个具体的问题（如"分析 AAPL"）
- 或者更清楚地描述您想了解的内容

我很乐意帮助您！"""
