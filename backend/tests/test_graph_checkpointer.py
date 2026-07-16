# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

import pytest

from backend.graph import checkpointer as checkpointer_mod


def _reset_bundle() -> None:
    checkpointer_mod.reset_checkpointer_caches()


def test_checkpointer_memory_nonpersistent(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "memory")
    _reset_bundle()
    try:
        info = checkpointer_mod.get_graph_checkpointer_info()
        assert info["backend"] == "memory"
        assert info["persistent"] is False
        assert info["location"] is None
    finally:
        _reset_bundle()


def test_async_checkpointer_memory_nonpersistent(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "memory")
    _reset_bundle()
    try:
        bundle = asyncio.run(checkpointer_mod.aget_checkpointer_bundle())
        assert bundle.info.backend == "memory"
        assert bundle.info.persistent is False
        info = checkpointer_mod.get_graph_checkpointer_info()
        assert info["location"] is None
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


def test_checkpointer_postgres_requires_dsn(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "postgres")
    monkeypatch.delenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "false")
    _reset_bundle()
    try:
        with pytest.raises(ValueError, match="LANGGRAPH_CHECKPOINT_POSTGRES_DSN"):
            checkpointer_mod.get_checkpointer_bundle()
    finally:
        _reset_bundle()


def test_production_rejects_memory_backend(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "memory")
    _reset_bundle()
    try:
        with pytest.raises(ValueError, match="必须为 postgres"):
            checkpointer_mod.get_checkpointer_bundle()
    finally:
        _reset_bundle()


def test_production_rejects_memory_fallback(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_BACKEND", "postgres")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "true")
    _reset_bundle()
    try:
        with pytest.raises(ValueError, match="禁止 LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK"):
            checkpointer_mod.get_checkpointer_bundle()
    finally:
        _reset_bundle()
