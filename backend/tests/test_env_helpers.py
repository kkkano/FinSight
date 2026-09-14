# -*- coding: utf-8 -*-
"""环境变量解析工具的统一契约。"""

import pytest

from backend.utils.env import env_bool, env_csv, env_float, env_int, env_str


def test_env_str_uses_trimmed_value_or_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_STR", "  value  ")
    assert env_str("FINSIGHT_TEST_STR", "fallback") == "value"

    monkeypatch.setenv("FINSIGHT_TEST_STR", "   ")
    assert env_str("FINSIGHT_TEST_STR", "fallback") == "fallback"

    monkeypatch.delenv("FINSIGHT_TEST_STR", raising=False)
    assert env_str("FINSIGHT_TEST_STR", "fallback") == "fallback"


def test_env_int_parses_value_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_INT", "42")
    assert env_int("FINSIGHT_TEST_INT", 7) == 42

    monkeypatch.setenv("FINSIGHT_TEST_INT", "invalid")
    assert env_int("FINSIGHT_TEST_INT", 7) == 7

    monkeypatch.delenv("FINSIGHT_TEST_INT", raising=False)
    assert env_int("FINSIGHT_TEST_INT", 7) == 7


def test_env_float_parses_value_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_FLOAT", "2.5")
    assert env_float("FINSIGHT_TEST_FLOAT", 1.25) == 2.5

    monkeypatch.setenv("FINSIGHT_TEST_FLOAT", "invalid")
    assert env_float("FINSIGHT_TEST_FLOAT", 1.25) == 1.25

    monkeypatch.delenv("FINSIGHT_TEST_FLOAT", raising=False)
    assert env_float("FINSIGHT_TEST_FLOAT", 1.25) == 1.25


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_env_bool_accepts_only_documented_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_BOOL", value)
    assert env_bool("FINSIGHT_TEST_BOOL") is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "unexpected", ""])
def test_env_bool_rejects_other_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_BOOL", value)
    assert env_bool("FINSIGHT_TEST_BOOL", True) is False


def test_env_bool_uses_default_only_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINSIGHT_TEST_BOOL", raising=False)
    assert env_bool("FINSIGHT_TEST_BOOL", True) is True
    assert env_bool("FINSIGHT_TEST_BOOL", False) is False


def test_env_csv_trims_items_and_drops_empty_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSIGHT_TEST_CSV", " alpha, beta ,, gamma ")
    assert env_csv("FINSIGHT_TEST_CSV") == ["alpha", "beta", "gamma"]

    monkeypatch.delenv("FINSIGHT_TEST_CSV", raising=False)
    assert env_csv("FINSIGHT_TEST_CSV", " one, two ") == ["one", "two"]
