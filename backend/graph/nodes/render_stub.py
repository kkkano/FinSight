# -*- coding: utf-8 -*-
"""DEPRECATED shim（WP3-T6）：渲染节点已改名 render_node（它从来不是 stub）。
保留到 WP3 Task 8 统一删除。monkeypatch 请打新家 backend.graph.nodes.render_node。"""
from backend.graph.nodes.render_node import *  # noqa: F401,F403
from backend.graph.nodes.render_node import render_node as render_stub  # noqa: F401
