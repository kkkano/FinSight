"""冻结镜像环境预检；分发版本、工具模块与解释器证据不含配置值。"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata as metadata
import json
from pathlib import Path
import pkgutil
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def inspect_environment():
    distributions = {canonicalize_name(dist.metadata["Name"]): dist.version for dist in metadata.distributions()}
    import backend.tools as tools
    modules = []
    for item in sorted(pkgutil.iter_modules(tools.__path__), key=lambda row: row.name):
        name = "backend.tools." + item.name
        try:
            importlib.import_module(name)
            modules.append({"module": name, "imported": True})
        except Exception as exc:
            modules.append({"module": name, "imported": False, "exception_type": type(exc).__name__})
    extra_modules = ["backend.services.market_data_gateway", "backend.agent_runtime.registry",
                     "backend.agent_runtime.model", "backend.agent_runtime.adapters",
                     "backend.agent_runtime.data", "backend.analysis_worker.protocol",
                     "agent_eval.baseline_runtime.tools", "pandas_market_calendars", "exchange_calendars"]
    for name in extra_modules:
        try:
            importlib.import_module(name)
            modules.append({"module": name, "imported": True})
        except Exception as exc:
            modules.append({"module": name, "imported": False, "exception_type": type(exc).__name__})
    return {"python_executable": sys.executable, "python_version": sys.version,
            "python_prefix": sys.prefix,
            "python_binary_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            "distributions": dict(sorted(distributions.items())), "module_imports": modules}


def validate_environment(profile, production_manifest: Path, runtime_requirements: Path):
    production = json.loads(Path(production_manifest).read_text(encoding="utf-8"))
    expected = {}
    for line in production["pip_freeze"].splitlines():
        requirement = Requirement(line)
        expected[canonicalize_name(requirement.name)] = str(requirement.specifier).removeprefix("==")
    rows = [{"name": name, "expected": version, "actual": profile["distributions"].get(name),
             "matched": profile["distributions"].get(name) == version} for name, version in sorted(expected.items())]
    requirements = []
    for line in Path(runtime_requirements).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        actual = profile["distributions"].get(canonicalize_name(requirement.name))
        requirements.append({"name": requirement.name, "specifier": str(requirement.specifier), "actual": actual,
                             "satisfied": actual is not None and requirement.specifier.contains(actual)})
    imports_passed = all(row["imported"] for row in profile["module_imports"])
    binary_matches = profile["python_binary_sha256"] == production["python_binary_sha256"]
    return {"production_manifest_sha256": hashlib.sha256(Path(production_manifest).read_bytes()).hexdigest(),
            "runtime_requirements_sha256": hashlib.sha256(Path(runtime_requirements).read_bytes()).hexdigest(),
            "distribution_rows": rows, "runtime_requirements": requirements,
            "imports_passed": imports_passed, "binary_matches_production": binary_matches,
            "passed": all(row["matched"] for row in rows) and all(row["satisfied"] for row in requirements)
                      and imports_passed and binary_matches}
