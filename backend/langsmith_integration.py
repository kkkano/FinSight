#!/usr/bin/env python3
"""
FinSight LangSmith 集成模块
提供运行追踪、事件记录和可观测性功能
支持异步上报，不阻塞主分析流程
"""

import logging

logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-


import os
import time
import uuid
import atexit
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import wraps

# ============================================
# 配置
# ============================================

# 从环境变量读取配置
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "FinSight")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
ENABLE_LANGSMITH = os.getenv("ENABLE_LANGSMITH", "false").lower() in ("true", "1", "yes")

# 线程池用于异步上报
_executor: Optional[ThreadPoolExecutor] = None
_client: Optional[Any] = None
_initialized: bool = False


# ============================================
# 数据结构
# ============================================

@dataclass
class RunContext:
    """运行上下文，用于追踪单次分析"""
    run_id: str
    name: str
    start_time: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    status: str = "running"
    error: Optional[str] = None
    outputs: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "run_id": self.run_id,
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "metadata": self.metadata,
            "events": self.events,
            "tool_calls": self.tool_calls,
            "status": self.status,
            "error": self.error,
            "outputs": self.outputs
        }


# ============================================
# 初始化
# ============================================

def init_langsmith(
    api_key: Optional[str] = None,
    project: Optional[str] = None,
    endpoint: Optional[str] = None
) -> bool:
    """
    初始化 LangSmith 客户端
    
    Args:
        api_key: LangSmith API 密钥（可选，默认从环境变量读取）
        project: 项目名称（可选，默认从环境变量读取）
        endpoint: API 端点（可选，默认从环境变量读取）
        
    Returns:
        是否初始化成功
    """
    global _client, _executor, _initialized, LANGSMITH_API_KEY, LANGSMITH_PROJECT
    
    # 使用参数或环境变量
    api_key = api_key or LANGSMITH_API_KEY
    project = project or LANGSMITH_PROJECT
    endpoint = endpoint or LANGSMITH_ENDPOINT
    
    if not api_key:
        logger.info("⚠️  LangSmith: 未配置 API Key，追踪功能已禁用")
        logger.info("   设置环境变量 LANGSMITH_API_KEY 启用追踪")
        return False
    
    try:
        # 尝试导入 langsmith
        from langsmith import Client
        
        # 创建客户端
        _client = Client(
            api_key=api_key,
            api_url=endpoint
        )
        
        # 设置项目
        os.environ["LANGCHAIN_PROJECT"] = project
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = api_key
        
        # 创建线程池
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="langsmith_")
        
        # 注册退出清理
        atexit.register(_cleanup)
        
        _initialized = True
        logger.info(f"✅ LangSmith 初始化成功")
        logger.info(f"   项目: {project}")
        logger.info(f"   端点: {endpoint}")
        
        return True
        
    except ImportError:
        logger.info("⚠️  LangSmith: langsmith 包未安装")
        logger.info("   运行: pip install langsmith")
        return False
        
    except Exception as e:
        logger.info(f"⚠️  LangSmith 初始化失败: {e}")
        return False


def _cleanup():
    """清理资源"""
    global _executor
    if _executor:
        _executor.shutdown(wait=True, cancel_futures=False)
        _executor = None


def is_enabled() -> bool:
    """检查 LangSmith 是否已启用"""
    return _initialized and _client is not None


# ============================================
# 运行追踪
# ============================================

def start_run(
    name: str,
    query: str,
    metadata: Optional[Dict[str, Any]] = None
) -> RunContext:
    """
    开始一个新的追踪运行
    
    Args:
        name: 运行名称
        query: 用户查询
        metadata: 额外元数据
        
    Returns:
        RunContext 对象
    """
    run_id = str(uuid.uuid4())
    
    run = RunContext(
        run_id=run_id,
        name=name,
        start_time=datetime.now(),
        metadata={
            "query": query,
            "project": LANGSMITH_PROJECT,
            **(metadata or {})
        }
    )
    
    # 异步上报开始事件
    if is_enabled():
        _submit_async(_report_run_start, run)
    
    return run


def log_event(
    run: RunContext,
    event_type: str,
    payload: Dict[str, Any]
) -> None:
    """
    记录事件（异步）
    
    Args:
        run: 运行上下文
        event_type: 事件类型（如 'tool_start', 'tool_end', 'llm_start'）
        payload: 事件数据
    """
    event = {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        "payload": payload
    }
    
    run.events.append(event)
    
    # 特殊处理工具调用计数
    if event_type == "tool_end":
        run.tool_calls += 1
    
    # 异步上报
    if is_enabled():
        _submit_async(_report_event, run.run_id, event)


def finish_run(
    run: RunContext,
    status: str = "success",
    outputs: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> Dict[str, Any]:
    """
    完成运行追踪
    
    Args:
        run: 运行上下文
        status: 状态（'success' 或 'error'）
        outputs: 输出结果
        error: 错误信息（如果有）
        
    Returns:
        运行摘要
    """
    run.status = status
    run.outputs = outputs
    run.error = error
    
    # 计算耗时
    duration = (datetime.now() - run.start_time).total_seconds()
    
    summary = {
        "run_id": run.run_id,
        "name": run.name,
        "status": status,
        "duration_seconds": duration,
        "tool_calls": run.tool_calls,
        "events_count": len(run.events),
        "error": error
    }
    
    # 异步上报完成
    if is_enabled():
        _submit_async(_report_run_end, run, summary)
    
    return summary


# ============================================
# 内部上报函数
# ============================================

def _submit_async(fn, *args, **kwargs):
    """提交异步任务"""
    if _executor:
        try:
            _executor.submit(fn, *args, **kwargs)
        except Exception:
            pass  # 静默失败，不影响主流程


def _report_run_start(run: RunContext):
    """上报运行开始"""
    if not _client:
        return
    try:
        # LangSmith 通过环境变量自动追踪 LangChain 运行
        # 这里可以添加自定义的运行元数据
        # 实际追踪由 LangChain 的内置 tracing 处理
        pass
    except Exception as e:
        _log_error(f"上报运行开始失败: {e}")


def _report_event(run_id: str, event: Dict[str, Any]):
    """上报事件"""
    if not _client:
        return
    try:
        # 事件通过 LangChain 的 callback 系统自动上报
        pass
    except Exception as e:
        _log_error(f"上报事件失败: {e}")


def _report_run_end(run: RunContext, summary: Dict[str, Any]):
    """上报运行结束"""
    if not _client:
        return
    try:
        # 运行结束通过 LangChain 的内置 tracing 处理
        pass
    except Exception as e:
        _log_error(f"上报运行结束失败: {e}")


def _log_error(msg: str):
    """记录错误（静默）"""
    # 可以写入日志文件而不是打印
    pass


# ============================================
# 装饰器
# ============================================

def trace_analysis(name: str = "FinSight Analysis"):
    """
    追踪分析的装饰器
    
    用法:
        @trace_analysis("My Analysis")
        def my_analysis(query: str) -> str:
            ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(query: str, *args, **kwargs):
            run = start_run(name, query)
            try:
                result = fn(query, *args, **kwargs)
                finish_run(run, status="success", outputs={"result": result[:500] if isinstance(result, str) else str(result)[:500]})
                return result
            except Exception as e:
                finish_run(run, status="error", error=str(e))
                raise
        return wrapper
    return decorator


# ============================================
# 回调处理器（用于集成到 streaming_support）
# ============================================

class LangSmithCallbackMixin:
    """
    LangSmith 回调混入类
    可以混入到 FinancialStreamingCallbackHandler 中
    """
    
    def __init__(self):
        self._langsmith_run: Optional[RunContext] = None
    
    def langsmith_on_chain_start(self, query: str, metadata: Optional[Dict] = None):
        """Chain 开始时初始化追踪"""
        if is_enabled():
            self._langsmith_run = start_run(
                name=f"FinSight: {query[:50]}...",
                query=query,
                metadata=metadata
            )
    
    def langsmith_on_tool_start(self, tool_name: str, input_str: str):
        """工具开始时记录"""
        if self._langsmith_run:
            log_event(self._langsmith_run, "tool_start", {
                "tool": tool_name,
                "input": input_str[:200] if input_str else ""
            })
    
    def langsmith_on_tool_end(self, tool_name: str, output: str):
        """工具结束时记录"""
        if self._langsmith_run:
            log_event(self._langsmith_run, "tool_end", {
                "tool": tool_name,
                "output": output[:200] if output else ""
            })
    
    def langsmith_on_llm_start(self, step: int):
        """LLM 开始时记录"""
        if self._langsmith_run:
            log_event(self._langsmith_run, "llm_start", {
                "step": step
            })
    
    def langsmith_on_chain_end(self, outputs: Optional[Dict] = None, success: bool = True, error: Optional[str] = None):
        """Chain 结束时完成追踪"""
        if self._langsmith_run:
            finish_run(
                self._langsmith_run,
                status="success" if success else "error",
                outputs=outputs,
                error=error
            )
            self._langsmith_run = None


# ============================================
# 便捷函数
# ============================================

def get_status() -> Dict[str, Any]:
    """获取 LangSmith 状态"""
    return {
        "enabled": is_enabled(),
        "initialized": _initialized,
        "project": LANGSMITH_PROJECT,
        "has_api_key": bool(LANGSMITH_API_KEY)
    }


def quick_init() -> bool:
    """
    快速初始化（使用环境变量配置）
    
    Returns:
        是否成功
    """
    if not ENABLE_LANGSMITH:
        return False
    return init_langsmith()


# ============================================
# 导出
# ============================================

__all__ = [
    # 初始化
    "init_langsmith",
    "quick_init",
    "is_enabled",
    "get_status",
    
    # 运行追踪
    "start_run",
    "log_event", 
    "finish_run",
    "RunContext",
    
    # 装饰器
    "trace_analysis",
    
    # 回调混入
    "LangSmithCallbackMixin",
    
    # 配置
    "ENABLE_LANGSMITH",
    "LANGSMITH_PROJECT",
]