"""按归档清单加载旧模块；生产入口不安装此加载器。"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def verify_manifest() -> dict:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for relative, row in manifest["files"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"reference_source_changed:{relative}")
    for row in manifest["protected_files"]:
        if hashlib.sha256((REPO / row["file"]).read_bytes()).hexdigest() != row["expected_sha256"]:
            raise ValueError(f"frozen_forecast_source_changed:{row['file']}")
    return manifest


class ReferenceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, modules: dict[str, str]):
        self.modules = modules

    def find_spec(self, fullname, path=None, target=None):
        relative = self.modules.get(fullname)
        if relative is None:
            return None
        source = ROOT / relative
        locations = [str(source.parent)] if source.name == "__init__.py" else None
        return importlib.util.spec_from_file_location(fullname, source, submodule_search_locations=locations)


def activate(*, include_tests: bool = False) -> ReferenceFinder:
    """必须在旧模块导入前调用；不同runtime使用不同进程。"""
    manifest = verify_manifest()
    modules = {name: relative for name, relative in manifest["modules"].items()
               if include_tests or manifest["files"][relative]["role"] in {"retired_production", "retired_function_host"}}
    for finder in sys.meta_path:
        if isinstance(finder, ReferenceFinder):
            finder.modules.update(modules)
            return finder
    for name, relative in modules.items():
        loaded = sys.modules.get(name)
        if loaded is not None and Path(getattr(loaded, "__file__", "")).resolve() != (ROOT / relative).resolve():
            raise ValueError(f"reference_must_be_selected_before_import:{name}")
    finder = ReferenceFinder(modules)
    sys.meta_path.insert(0, finder)
    return finder
