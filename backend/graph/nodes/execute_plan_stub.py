# -*- coding: utf-8 -*-
"""DEPRECATED shim（WP3-T6）：执行节点已改名 execute_plan_node（它从来不是 stub）。
保留到 WP3 Task 8 统一删除。monkeypatch 请打新家 backend.graph.nodes.execute_plan_node。"""
from backend.graph.nodes.execute_plan_node import *  # noqa: F401,F403
from backend.graph.nodes.execute_plan_node import (  # noqa: F401
    execute_plan_node as execute_plan_stub,
)
