# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from .registry import SkillRegistry, get_builtin_skill_registry
from .schema import SkillManifest, SkillSelection

_EXPLICIT_SKILL_RE = re.compile(r"^\s*/skill\s+([A-Za-z0-9_.:-]+)\b")


def extract_explicit_skill(query: str) -> str | None:
    match = _EXPLICIT_SKILL_RE.search(str(query or ""))
    if not match:
        return None
    return match.group(1).strip() or None


def _value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_value_matches(actual, item) for item in expected)
    if isinstance(actual, list):
        return any(_value_matches(item, expected) for item in actual)
    return str(actual or "").strip().lower() == str(expected or "").strip().lower()


def _score_manifest(facets: dict[str, Any], manifest: SkillManifest) -> tuple[float, list[str]]:
    required = manifest.required_facets or {}
    if not required:
        return 0.0, []
    matched: list[str] = []
    for key, expected in required.items():
        if _value_matches(facets.get(key), expected):
            matched.append(str(key))
    score = len(matched) / max(len(required), 1)
    return score, matched


def select_skill_for_facets(
    facets: dict[str, Any],
    *,
    registry: SkillRegistry | None = None,
    explicit_skill: str | None = None,
    threshold: float = 0.67,
) -> SkillSelection:
    skill_registry = registry or get_builtin_skill_registry()
    manifests = skill_registry.as_dict()
    requested = str(explicit_skill or "").strip()
    if requested and requested in manifests:
        return SkillSelection(
            selected_skill=requested,
            candidates=[{"name": requested, "score": 1.0, "matched_facets": ["explicit"]}],
            reason="explicit_skill",
        )

    candidates: list[dict[str, Any]] = []
    for manifest in skill_registry.all():
        score, matched = _score_manifest(facets, manifest)
        if score <= 0:
            continue
        candidates.append({"name": manifest.name, "score": round(score, 4), "matched_facets": matched})
    candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("name") or "")))
    if candidates and float(candidates[0].get("score") or 0.0) >= threshold:
        return SkillSelection(
            selected_skill=str(candidates[0].get("name") or ""),
            candidates=candidates,
            reason="facet_match",
        )
    return SkillSelection(selected_skill=None, candidates=candidates, reason="no_skill_match")
