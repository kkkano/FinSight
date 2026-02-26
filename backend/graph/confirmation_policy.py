# -*- coding: utf-8 -*-
"""
Unified confirmation strategy policy.
"""

from __future__ import annotations

from typing import Any, Literal


ConfirmationMode = Literal["auto", "required", "skip"]
_ALLOWED_MODES = {"auto", "required", "skip"}


def parse_confirmation_mode(value: Any) -> ConfirmationMode | None:
    text = str(value or "").strip().lower()
    if text in _ALLOWED_MODES:
        return text  # type: ignore[return-value]
    return None


def normalize_confirmation_mode(value: Any, *, default: ConfirmationMode = "auto") -> ConfirmationMode:
    parsed = parse_confirmation_mode(value)
    return parsed if parsed is not None else default


def should_require_confirmation(
    *,
    require_confirmation: Any,
    confirmation_mode: Any,
    output_mode: Any,
) -> bool:
    # Highest priority: explicit require_confirmation.
    if require_confirmation is False:
        return False
    if require_confirmation is True:
        return True

    mode = normalize_confirmation_mode(confirmation_mode, default="auto")
    if mode == "skip":
        return False
    if mode == "required":
        return True

    return str(output_mode or "").strip().lower() == "investment_report"


__all__ = [
    "ConfirmationMode",
    "normalize_confirmation_mode",
    "parse_confirmation_mode",
    "should_require_confirmation",
]
