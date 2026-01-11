# -*- coding: utf-8 -*-
"""
ContextManager - 对话上下文管理
负责维护对话历史、用户偏好、累积数据、LLM 消息格式化
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from collections import deque
from enum import Enum
import re


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
        self.current_focus_market: Optional[str] = None
        self.current_focus_exchange: Optional[str] = None
        self.market_preference: Optional[str] = None
        self.pending_clarification: Optional[Dict[str, Any]] = None
        self.company_memory: Dict[str, Dict[str, Any]] = {}
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
        
        # 更新当前关注焦点 / 澄清状态
        if metadata:
            market_hint = self._extract_market_hint(query)
            if market_hint:
                self.market_preference = market_hint

            tickers = metadata.get('tickers') or []
            if tickers:
                ticker = tickers[0]
                self._update_focus_from_ticker(ticker, metadata)
                self._remember_companies(metadata, ticker)
                self.pending_clarification = None
            elif metadata.get('ticker_candidates'):
                self._set_pending_clarification(metadata, query, intent)
        
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

    def preprocess_query(self, query: str) -> Dict[str, Any]:
        """Preprocess user query with pending clarification and memory."""
        market_hint = self._extract_market_hint(query)
        if market_hint:
            self.market_preference = market_hint

        resolved = self._resolve_pending_clarification(query, market_hint)
        if resolved:
            return resolved

        updated_query = self._apply_company_memory(query, market_hint)
        return {"query": updated_query, "market_hint": market_hint}

    def _set_pending_clarification(self, metadata: Dict[str, Any], query: str, intent: str) -> None:
        candidates = metadata.get("ticker_candidates") or []
        if not candidates:
            return
        company_hint = None
        for key in ("company_names", "company_mentions"):
            items = metadata.get(key) or []
            if items:
                company_hint = items[0]
                break
        self.pending_clarification = {
            "company_hint": company_hint,
            "candidates": candidates,
            "original_query": query,
            "intent": intent,
            "created_at": datetime.now(),
        }

    def _pending_expired(self, pending: Dict[str, Any], ttl_seconds: int = 600) -> bool:
        created_at = pending.get("created_at")
        if not isinstance(created_at, datetime):
            return False
        return (datetime.now() - created_at) > timedelta(seconds=ttl_seconds)

    def _resolve_pending_clarification(self, query: str, market_hint: Optional[str]) -> Optional[Dict[str, Any]]:
        pending = self.pending_clarification
        if not pending:
            return None
        if self._pending_expired(pending):
            self.pending_clarification = None
            return None

        candidates = pending.get("candidates") or []
        if not candidates:
            return None

        matched = self._match_candidate_by_symbol(query, candidates)
        reason = "explicit_ticker" if matched else None

        if matched is None:
            index = self._extract_selection_index(query)
            if index is not None and 0 <= index < len(candidates):
                matched = candidates[index]
                reason = "index_choice"

        if matched is None:
            hint = market_hint or self.market_preference
            if hint:
                matched = self._match_candidate_by_market(candidates, hint)
                if matched:
                    reason = "market_hint"

        if matched is None:
            return None

        ticker = matched.get("symbol") if isinstance(matched, dict) else str(matched)
        if not ticker:
            return None

        base_query = pending.get("original_query") or query
        company_hint = pending.get("company_hint")
        if company_hint and company_hint.lower() in query.lower() and len(query) > len(base_query):
            base_query = query
        resolved_query = self._inject_ticker(base_query, pending.get("company_hint"), ticker)

        self.pending_clarification = None
        self._remember_company(pending.get("company_hint"), ticker, {"matches": [matched]})
        self._update_focus_from_ticker(ticker, {"ticker_resolution": {"matches": [matched]}})

        return {
            "query": resolved_query,
            "selected_ticker": ticker,
            "selection_reason": reason,
            "market_hint": market_hint,
        }

    def _match_candidate_by_symbol(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        query_upper = query.upper()
        for item in candidates:
            symbol = item.get("symbol") if isinstance(item, dict) else None
            if symbol and symbol.upper() in query_upper:
                return item
        return None

    def _extract_selection_index(self, query: str) -> Optional[int]:
        query = query.strip()
        match = re.search(r"(?:第\\s*([1-5]))|\\b([1-5])\\b", query)
        if match:
            value = match.group(1) or match.group(2)
            try:
                return int(value) - 1
            except Exception:
                return None
        cn_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4}
        for key, idx in cn_map.items():
            if f"第{key}" in query or query == key:
                return idx
        return None

    def _match_candidate_by_market(self, candidates: List[Dict[str, Any]], market: str) -> Optional[Dict[str, Any]]:
        for item in candidates:
            if self._candidate_matches_market(item, market):
                return item
        return None

    def _candidate_matches_market(self, candidate: Dict[str, Any], market: str) -> bool:
        symbol = (candidate.get("symbol") or "").upper()
        exchange = (candidate.get("primaryExchange") or "").upper()
        description = (candidate.get("description") or "").upper()
        blob = f"{symbol} {exchange} {description}"

        if market == "US":
            return any(tag in blob for tag in ["NYSE", "NASDAQ", "OTC", "US", "ADR"]) or symbol.endswith(".US")
        if market == "FR":
            return any(tag in blob for tag in ["PAR", "EURONEXT", "PARIS"]) or symbol.endswith(".PA")
        if market == "UK":
            return any(tag in blob for tag in ["LSE", "LONDON"]) or symbol.endswith(".L")
        if market == "HK":
            return any(tag in blob for tag in ["HK", "HKEX"]) or symbol.endswith(".HK")
        if market == "CN":
            return any(tag in blob for tag in ["SSE", "SZSE", "SHANGHAI", "SHENZHEN"]) or symbol.endswith((".SS", ".SZ"))
        if market == "JP":
            return any(tag in blob for tag in ["TSE", "TOKYO"]) or symbol.endswith(".T")
        if market == "EU":
            return "EURONEXT" in blob or symbol.endswith(".PA")
        return False

    def _extract_market_hint(self, query: str) -> Optional[str]:
        lowered = query.lower()
        hint_map = {
            "US": ["美国", "美股", "nyse", "nasdaq", "otc", "adr", "us", "u.s"],
            "FR": ["法国", "法股", "巴黎", "euronext", "paris", ".pa"],
            "UK": ["英国", "英股", "伦敦", "lse", "london", ".l"],
            "HK": ["香港", "港股", "hkex", ".hk"],
            "CN": ["中国", "a股", "沪", "深", "上证", "深证", "sse", "szse", ".ss", ".sz"],
            "JP": ["日本", "日股", "东京", "tse", ".t"],
            "EU": ["欧洲", "欧股", "eu", "euronext"],
        }
        for market, keys in hint_map.items():
            for key in keys:
                if key.isascii():
                    if key in lowered:
                        return market
                else:
                    if key in query:
                        return market
        return None

    def _apply_company_memory(self, query: str, market_hint: Optional[str]) -> str:
        if not self.company_memory:
            return query
        effective_hint = market_hint or self.market_preference
        normalized_query = self._normalize_company_name(query) or ""
        for key, info in self.company_memory.items():
            name = info.get("name")
            ticker = info.get("ticker")
            if not name or not ticker:
                continue
            if ticker.upper() in query.upper():
                return query
            if effective_hint and info.get("market") and info.get("market") != effective_hint:
                continue
            if (name.lower() in query.lower()) or (key and key in normalized_query):
                return self._inject_ticker(query, name, ticker)
        return query

    def _inject_ticker(self, base_query: str, company_hint: Optional[str], ticker: str) -> str:
        if company_hint:
            if company_hint in base_query:
                return base_query.replace(company_hint, ticker)
            try:
                return re.sub(re.escape(company_hint), ticker, base_query, flags=re.IGNORECASE)
            except Exception:
                pass
        if ticker.upper() not in base_query.upper():
            return f"{ticker} {base_query}".strip()
        return base_query

    def _normalize_company_name(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", name.strip().lower())
        return compact or None

    def _remember_companies(self, metadata: Dict[str, Any], ticker: str) -> None:
        names = []
        names.extend(metadata.get("company_names") or [])
        names.extend(metadata.get("company_mentions") or [])
        for name in names:
            self._remember_company(name, ticker, metadata.get("ticker_resolution"))

    def _remember_company(self, name: Optional[str], ticker: str, extra: Optional[Dict[str, Any]] = None) -> None:
        key = self._normalize_company_name(name)
        if not key:
            return
        exchange = None
        market = None
        if isinstance(extra, dict):
            matches = extra.get("matches") or []
            for item in matches:
                symbol = item.get("symbol") if isinstance(item, dict) else None
                if symbol and symbol.upper() == ticker.upper():
                    exchange = item.get("primaryExchange") or item.get("exchange")
                    break
        if exchange:
            market = self._infer_market_from_exchange(exchange)
        if not market:
            market = self._infer_market_from_ticker(ticker)
        self.company_memory[key] = {
            "name": name,
            "ticker": ticker,
            "market": market,
            "exchange": exchange,
            "updated_at": datetime.now().isoformat(),
        }
        if name and " " in name:
            short_name = name.split(" ")[0]
            short_key = self._normalize_company_name(short_name)
            if short_key and short_key not in self.company_memory:
                self.company_memory[short_key] = {
                    "name": short_name,
                    "ticker": ticker,
                    "market": market,
                    "exchange": exchange,
                    "updated_at": datetime.now().isoformat(),
                }

    def _infer_market_from_exchange(self, exchange: str) -> Optional[str]:
        ex = exchange.upper()
        if any(tag in ex for tag in ["NYSE", "NASDAQ", "OTC", "AMEX"]):
            return "US"
        if any(tag in ex for tag in ["PAR", "EURONEXT", "PARIS"]):
            return "FR"
        if "LSE" in ex or "LONDON" in ex:
            return "UK"
        if "HK" in ex:
            return "HK"
        if "SSE" in ex or "SZSE" in ex:
            return "CN"
        if "TSE" in ex or "TOKYO" in ex:
            return "JP"
        return None

    def _infer_market_from_ticker(self, ticker: str) -> Optional[str]:
        parts = ticker.upper().split(".")
        if len(parts) >= 2:
            suffix = parts[-1]
            if suffix in ("US", "NYSE", "NASDAQ", "OTC"):
                return "US"
            if suffix in ("PA", "PAR"):
                return "FR"
            if suffix in ("L", "LSE"):
                return "UK"
            if suffix == "HK":
                return "HK"
            if suffix in ("SS", "SZ"):
                return "CN"
            if suffix in ("T", "TSE"):
                return "JP"
        return None

    def _update_focus_from_ticker(self, ticker: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.current_focus = ticker
        if metadata:
            names = metadata.get("company_names") or metadata.get("company_mentions") or []
            if names:
                self.current_focus_name = names[0]
            resolution = metadata.get("ticker_resolution")
            if isinstance(resolution, dict):
                for item in resolution.get("matches") or []:
                    symbol = item.get("symbol") if isinstance(item, dict) else None
                    if symbol and symbol.upper() == ticker.upper():
                        self.current_focus_exchange = item.get("primaryExchange") or item.get("exchange")
                        break
        market = self._infer_market_from_ticker(ticker)
        if market:
            self.current_focus_market = market
            self.market_preference = market
    
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
        
        focus_info = ""
        if self.current_focus:
            focus_info += f"\n当前焦点: {self.current_focus}"
        if self.market_preference:
            focus_info += f"\n市场偏好: {self.market_preference}"
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
        
        pronouns = [
            '它', '那个', '这个', '该股票', '这支股票', '那支股票', '该股', '这只', '那只',
            '这家公司', '该公司', '那家公司', '这家', '那家',
            'it', 'that', 'this stock', 'the stock', 'this company', 'the company'
        ]
        
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
        self.current_focus_market = None
        self.current_focus_exchange = None
        self.market_preference = None
        self.pending_clarification = None
        self.company_memory.clear()
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
            'current_focus_market': self.current_focus_market,
            'current_focus_exchange': self.current_focus_exchange,
            'market_preference': self.market_preference,
            'pending_clarification': bool(self.pending_clarification),
            'company_memory_count': len(self.company_memory),
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
