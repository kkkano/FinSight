# -*- coding: utf-8 -*-
"""
ContextManager - 对话上下文管理
负责维护对话历史、用户偏好、累积数据、LLM 消息格式化
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from collections import deque
from enum import Enum


class MessageRole(Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ConversationTurn:
    """对话轮次"""
    query: str
    intent: str
    response: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'query': self.query,
            'intent': self.intent,
            'response': self.response[:200] + '...' if self.response and len(self.response) > 200 else self.response,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
            'tool_calls_count': len(self.tool_calls),
        }


class ContextManager:
    """
    对话上下文管理器
    
    功能：
    - 维护对话历史（最近 N 轮）
    - 追踪当前关注的股票
    - 解析指代词（"它"→当前股票）
    - 缓存分析过程中的数据
    - 格式化 LLM 消息
    """
    
    def __init__(self, max_turns: int = 10, max_tokens: int = 4000):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.history: deque = deque(maxlen=max_turns)
        self.current_focus: Optional[str] = None  # 当前关注的股票代码
        self.current_focus_name: Optional[str] = None  # 当前关注的公司名称
        self.user_preferences: Dict[str, Any] = {
            'language': 'zh',  # 默认中文
            'detail_level': 'medium',  # low/medium/high
            'risk_tolerance': 'medium',  # low/medium/high
        }
        self.accumulated_data: Dict[str, Any] = {}  # 已收集的数据缓存
        self.session_start: datetime = datetime.now()
        self.last_long_response: Optional[str] = None  # 最近的长文本（报告/长回答）
    
    def add_turn(
        self, 
        query: str, 
        intent: str, 
        response: str = None, 
        metadata: Dict = None,
        tool_calls: List[Dict] = None
    ) -> ConversationTurn:
        """
        添加对话轮次
        
        Args:
            query: 用户查询
            intent: 识别的意图
            response: Agent 响应
            metadata: 额外元数据（如提取的股票代码）
            tool_calls: 工具调用记录
        """
        turn = ConversationTurn(
            query=query,
            intent=intent,
            response=response,
            metadata=metadata or {},
            tool_calls=tool_calls or []
        )
        self.history.append(turn)
        
        # 更新当前关注焦点
        if metadata:
            if 'tickers' in metadata and metadata['tickers']:
                self.current_focus = metadata['tickers'][0]
            if 'company_name' in metadata:
                self.current_focus_name = metadata['company_name']
        
        # 记录长文本供后续翻译/摘要
        if response and len(response) > 400:
            self.last_long_response = response
        
        return turn
    
    def update_last_response(self, response: str, tool_calls: List[Dict] = None) -> None:
        """更新最后一轮的响应"""
        if self.history:
            self.history[-1].response = response
            if tool_calls:
                self.history[-1].tool_calls = tool_calls
    
    def get_summary(self) -> str:
        """获取对话历史摘要（用于意图分类）"""
        if not self.history:
            return "无历史对话"
        
        recent = list(self.history)[-5:]  # 最近 5 轮
        summary_lines = []
        
        for turn in recent:
            summary_lines.append(f"- 用户({turn.intent}): {turn.query[:50]}{'...' if len(turn.query) > 50 else ''}")
            if turn.response:
                resp_preview = turn.response[:80] + '...' if len(turn.response) > 80 else turn.response
                summary_lines.append(f"  助手: {resp_preview}")
        
        focus_info = f"\n当前焦点: {self.current_focus}" if self.current_focus else ""
        return "\n".join(summary_lines) + focus_info
    
    def get_messages_for_llm(self, system_prompt: str = None) -> List[Dict[str, str]]:
        """
        获取 LLM 可用的消息列表
        
        Args:
            system_prompt: 系统提示词（可选）
            
        Returns:
            符合 OpenAI 消息格式的列表
        """
        messages = []
        
        # 添加系统提示词
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        # 添加对话历史
        for turn in self.history:
            messages.append({
                "role": "user",
                "content": turn.query
            })
            if turn.response:
                messages.append({
                    "role": "assistant",
                    "content": turn.response
                })
        
        return messages
    
    def get_context_for_llm(self) -> List[Dict[str, str]]:
        """获取 LLM 可用的上下文消息列表（不含系统提示词）"""
        return self.get_messages_for_llm(system_prompt=None)
    
    def get_last_n_turns(self, n: int = 3) -> List[ConversationTurn]:
        """获取最近 N 轮对话"""
        return list(self.history)[-n:]
    
    def get_last_response(self) -> Optional[str]:
        """获取上一轮的响应"""
        if self.history and len(self.history) >= 1:
            return self.history[-1].response
        return None
    
    def get_last_query(self) -> Optional[str]:
        """获取上一轮的查询"""
        if self.history and len(self.history) >= 1:
            return self.history[-1].query
        return None

    def get_last_long_response(self) -> Optional[str]:
        """获取最近的长文本（报告/长回答），若无缓存则从历史中挑最长一条"""
        if self.last_long_response:
            return self.last_long_response
        longest = None
        for turn in self.history:
            if turn.response and (longest is None or len(turn.response) > len(longest)):
                longest = turn.response
        return longest
    
    def resolve_reference(self, query: str) -> str:
        """
        解析指代词
        
        将"它"、"这个股票"等指代词替换为当前关注的股票
        
        Args:
            query: 原始查询
            
        Returns:
            解析后的查询
        """
        if not self.current_focus:
            return query
        
        pronouns = ['它', '那个', '这个', '该股票', '这支股票', '那支股票', 'it', 'that', 'this stock', 'the stock']
        
        resolved = query
        for pronoun in pronouns:
            if pronoun in query.lower():
                # 用股票代码替换
                resolved = resolved.replace(pronoun, self.current_focus)
                resolved = resolved.replace(pronoun.capitalize(), self.current_focus)
        
        return resolved
    
    def cache_data(self, key: str, data: Any) -> None:
        """
        缓存分析过程中获取的数据
        
        用于在同一对话中复用已获取的数据
        """
        self.accumulated_data[key] = {
            'data': data,
            'timestamp': datetime.now()
        }
    
    def get_cached_data(self, key: str, max_age_seconds: int = 300) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键
            max_age_seconds: 最大有效时间（秒）
        """
        if key not in self.accumulated_data:
            return None
        
        cached = self.accumulated_data[key]
        age = (datetime.now() - cached['timestamp']).total_seconds()
        
        if age > max_age_seconds:
            del self.accumulated_data[key]
            return None
        
        return cached['data']
    
    def get_all_cached_data(self) -> Dict[str, Any]:
        """获取所有缓存数据（用于报告生成）"""
        result = {}
        for key, cached in self.accumulated_data.items():
            result[key] = cached['data']
        return result
    
    def set_user_preference(self, key: str, value: Any) -> None:
        """设置用户偏好"""
        self.user_preferences[key] = value
    
    def get_user_preference(self, key: str, default: Any = None) -> Any:
        """获取用户偏好"""
        return self.user_preferences.get(key, default)
    
    def clear(self) -> None:
        """清空上下文"""
        self.history.clear()
        self.current_focus = None
        self.current_focus_name = None
        self.accumulated_data.clear()
    
    def clear_cache(self) -> None:
        """只清空缓存数据"""
        self.accumulated_data.clear()
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态（用于调试）"""
        return {
            'turns': len(self.history),
            'current_focus': self.current_focus,
            'current_focus_name': self.current_focus_name,
            'cached_data_keys': list(self.accumulated_data.keys()),
            'user_preferences': self.user_preferences,
            'session_duration_seconds': (datetime.now() - self.session_start).total_seconds(),
        }
    
    def get_focus_summary(self) -> str:
        """获取当前焦点的摘要描述"""
        if self.current_focus:
            name_part = f" ({self.current_focus_name})" if self.current_focus_name else ""
            return f"{self.current_focus}{name_part}"
        return "无特定焦点"
