# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.graph import checkpointer as checkpointer_mod


def _reset_bundle() -> None:
    checkpointer_mod.reset_checkpointer_caches()


def test_checkpointer_sqlite_persistent(tmp_path, monkeypatch):
    sqlite_file = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "sqlite")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SQLITE_PATH", str(sqlite_file))
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "true")
    _reset_bundle()
    try:
        info = checkpointer_mod.get_graph_checkpointer_info()
        assert info["backend"] == "sqlite"
        assert info["persistent"] is True
        assert Path(info["location"]).name == "checkpoints.sqlite"
    finally:
        _reset_bundle()


def test_async_checkpointer_sqlite_persistent(tmp_path, monkeypatch):
    sqlite_file = tmp_path / "async-checkpoints.sqlite"
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "sqlite")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SQLITE_PATH", str(sqlite_file))
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "true")
    _reset_bundle()
    try:
        bundle = asyncio.run(checkpointer_mod.aget_checkpointer_bundle())
        assert bundle.info.backend == "sqlite"
        assert bundle.info.persistent is True
        info = checkpointer_mod.get_graph_checkpointer_info()
        assert Path(info["location"]).name == "async-checkpoints.sqlite"
    finally:
        _reset_bundle()


def test_checkpointer_fallback_to_memory(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "unknown-backend")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "true")
    _reset_bundle()
    try:
        info = checkpointer_mod.get_graph_checkpointer_info()
        assert info["backend"] == "memory"
        assert info["persistent"] is False
        assert info["fallback_used"] is True
        assert isinstance(info["fallback_reason"], str) and info["fallback_reason"]
    finally:
        _reset_bundle()


def test_checkpointer_no_fallback_raises(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "unknown-backend")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "false")
    _reset_bundle()
    try:
        with pytest.raises(ValueError):
            checkpointer_mod.get_checkpointer_bundle()
    finally:
        _reset_bundle()
