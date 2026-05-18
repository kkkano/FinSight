# -*- coding: utf-8 -*-
"""外部 Agent 协议适配边界。"""

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
    "build_tool_registry",
    "dispatch_tool_call",
    "is_mcp_server_enabled",
    "list_mcp_tools",
]
