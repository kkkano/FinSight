# -*- coding: utf-8 -*-
"""外部 Agent 协议适配边界。"""

from backend.protocols.a2a_server import (
    build_agent_card,
    build_execute_request,
    get_task_artifacts,
    is_a2a_server_enabled,
    stream_task,
    submit_task,
)
from backend.protocols.mcp_server import (
    ReadOnlyToolRegistry,
    ToolSpec,
    build_tool_registry,
    dispatch_tool_call,
    is_mcp_server_enabled,
    list_mcp_tools,
)

__all__ = [
    "ReadOnlyToolRegistry",
    "ToolSpec",
    "build_agent_card",
    "build_execute_request",
    "build_tool_registry",
    "dispatch_tool_call",
    "get_task_artifacts",
    "is_a2a_server_enabled",
    "is_mcp_server_enabled",
    "list_mcp_tools",
    "stream_task",
    "submit_task",
]
