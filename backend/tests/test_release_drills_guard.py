# -*- coding: utf-8 -*-
"""SEC-05：release drill 的 subprocess 执行必须显式 env 开关放行，杜绝被服务路径意外触达。"""
import pytest


def test_run_drill_refuses_outside_cli(monkeypatch):
    monkeypatch.delenv("FINSIGHT_RELEASE_DRILL_ALLOWED", raising=False)
    from backend.services import release_drills

    with pytest.raises(RuntimeError, match="FINSIGHT_RELEASE_DRILL_ALLOWED"):
        release_drills._assert_drill_allowed()


def test_run_drill_allowed_with_env(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RELEASE_DRILL_ALLOWED", "true")
    from backend.services import release_drills

    release_drills._assert_drill_allowed()  # 不抛即通过
