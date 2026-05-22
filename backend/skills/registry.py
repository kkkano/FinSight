# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from .schema import SkillManifest


class SkillRegistry:
    def __init__(self, manifests: Iterable[SkillManifest] | None = None) -> None:
        self._manifests: dict[str, SkillManifest] = {}
        for manifest in manifests or []:
            self._manifests[manifest.name] = manifest

    @classmethod
    def from_directory(cls, path: str | Path) -> "SkillRegistry":
        root = Path(path)
        manifests: list[SkillManifest] = []
        if not root.exists():
            return cls()
        for file_path in sorted(root.glob("*.yaml")):
            try:
                raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    continue
                manifest = SkillManifest.from_mapping(raw)
                if manifest is not None:
                    manifests.append(manifest)
            except Exception:
                continue
        return cls(manifests)

    def get(self, name: str) -> SkillManifest | None:
        return self._manifests.get(str(name or "").strip())

    def all(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def as_dict(self) -> dict[str, SkillManifest]:
        return dict(self._manifests)


@lru_cache(maxsize=1)
def get_builtin_skill_registry() -> SkillRegistry:
    return SkillRegistry.from_directory(Path(__file__).resolve().parent / "builtin")
