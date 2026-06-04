# -*- coding: utf-8 -*-
"""P1续: conversation_store 路径锚定测试

验证默认存储路径锚定到仓库根 /data 或 FINSIGHT_DATA_DIR，
不受进程 CWD 影响（split-brain 防护，与 portfolio/monitor/cost_audit 同模式）。
"""

from pathlib import Path

from backend.services.conversation_store import ConversationStore, _store_path


def test_default_path_anchored_to_repo_root(monkeypatch):
    monkeypatch.delenv("CONVERSATION_STORE_PATH", raising=False)
    monkeypatch.delenv("FINSIGHT_DATA_DIR", raising=False)
    path = _store_path()
    # 应为绝对路径，且落在 <repo>/data 下，不是 CWD 相对的 ./data
    assert path.is_absolute()
    assert path.parent.name == "data"
    assert path.name == "conversations.json"


def test_finsight_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("CONVERSATION_STORE_PATH", raising=False)
    monkeypatch.setenv("FINSIGHT_DATA_DIR", str(tmp_path))
    path = _store_path()
    assert path == tmp_path / "conversations.json"


def test_explicit_store_path_takes_precedence(monkeypatch, tmp_path):
    custom = tmp_path / "custom.json"
    monkeypatch.setenv("CONVERSATION_STORE_PATH", str(custom))
    monkeypatch.setenv("FINSIGHT_DATA_DIR", str(tmp_path / "other"))
    assert _store_path() == custom


def test_path_independent_of_cwd(monkeypatch, tmp_path):
    """切换 CWD 后默认路径不变（核心 split-brain 防护）。"""
    monkeypatch.delenv("CONVERSATION_STORE_PATH", raising=False)
    monkeypatch.delenv("FINSIGHT_DATA_DIR", raising=False)
    p1 = _store_path()
    monkeypatch.chdir(tmp_path)
    p2 = _store_path()
    assert p1 == p2


def test_store_roundtrip_with_explicit_path(tmp_path):
    store = ConversationStore(path=tmp_path / "conv.json")
    store.upsert("sess-1", {"messages": [{"role": "user", "content": "hi"}], "title": "T"})
    got = store.get("sess-1")
    assert got is not None
    assert got["title"] == "T"
    assert (tmp_path / "conv.json").exists()
