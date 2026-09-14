#!/usr/bin/env python3
"""生成不含凭据的 FinSight 产品与架构基线。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}
SKIP_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "archive",
    "dist",
    "node_modules",
    "__pycache__",
}

FRONTEND_ROUTE_RE = re.compile(r"<Route\b[^>]*\bpath=[\"']([^\"']+)[\"']")

PRODUCTION_MARKERS = {
    "synthetic_price_fallback": re.compile(r"price_fallback(?:_hourly)?"),
    "runtime_create_table": re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", re.IGNORECASE),
    "legacy_intent_engine": re.compile(r"legacy_engine"),
    "dashboard_llm_scorer": re.compile(r"(?:insights_engine|dashboard\.scorers)"),
    "research_debate": re.compile(r"research_debate"),
    "removed_report_actions": re.compile(
        r"(?:exportPDF|/api/export/pdf|setReportFavorite|checkPriceDrift|compareReports|"
        r"/api/reports/(?:compare|price-drift)|is_favorite)"
    ),
}

STORAGE_SUFFIXES = {".db", ".json", ".sqlite", ".sqlite3"}


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def _iter_source_files(root: Path, relative: str) -> Iterable[Path]:
    base = root / relative
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        if "tests" in path.relative_to(root).parts:
            continue
        yield path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _line_count(paths: Iterable[Path]) -> int:
    count = 0
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            count += sum(1 for _ in handle)
    return count


def _locations(root: Path, pattern: re.Pattern[str], roots: Iterable[str]) -> list[str]:
    results: list[str] = []
    for relative in roots:
        for path in _iter_source_files(root, relative):
            for line_number, line in enumerate(_read(path).splitlines(), start=1):
                if pattern.search(line):
                    results.append(f"{path.relative_to(root).as_posix()}:{line_number}")
    return results


def _router_baseline(root: Path) -> dict[str, object]:
    from fastapi.routing import APIRoute

    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from backend.api.app_factory import create_app

    api_root = root / "backend" / "api"
    route_files = sorted(api_root.glob("*_router.py"))
    routes = [
        route
        for route in create_app().routes
        if isinstance(route, APIRoute) and route.include_in_schema
    ]
    router_tags = sorted({tag for route in routes for tag in (route.tags or [])})
    return {
        "router_modules": len(route_files),
        "registered_routers": router_tags,
        "registered_router_count": len(router_tags),
        "public_path_count": len({route.path for route in routes}),
        "public_operation_count": len(routes),
    }


def _frontend_baseline(root: Path) -> dict[str, object]:
    app_path = root / "frontend" / "src" / "App.tsx"
    paths = FRONTEND_ROUTE_RE.findall(_read(app_path)) if app_path.exists() else []
    redirect_routes = [path for path in paths if path in {"/", "*"}]
    product_routes = [path for path in paths if path not in {"/", "*"}]
    return {
        "route_count": len(product_routes),
        "routes": product_routes,
        "redirect_route_count": len(redirect_routes),
        "redirect_routes": redirect_routes,
    }


def _storage_baseline(root: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for relative in ("backend/data", "data"):
        base = root / relative
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in STORAGE_SUFFIXES:
                continue
            results.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                }
            )
    return results


def build_baseline(root: Path) -> dict[str, object]:
    scan_roots = ("backend", "frontend/src")
    marker_results = {
        name: _locations(root, pattern, scan_roots)
        for name, pattern in PRODUCTION_MARKERS.items()
    }
    loc_roots = (
        "backend/graph",
        "backend/agents",
        "backend/services",
        "backend/tools",
        "frontend/src/components",
    )
    source_lines = {
        relative: _line_count(_iter_source_files(root, relative)) for relative in loc_roots
    }
    status = _run_git(root, "status", "--porcelain")
    return {
        "schema_version": "finsight.product-baseline.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git": {
            "branch": _run_git(root, "branch", "--show-current"),
            "head": _run_git(root, "rev-parse", "HEAD"),
            "dirty_path_count": len(status.splitlines()) if status else 0,
        },
        "backend_api": _router_baseline(root),
        "frontend": _frontend_baseline(root),
        "source_lines": source_lines,
        "production_markers": {
            name: {"count": len(locations), "locations": locations}
            for name, locations in marker_results.items()
        },
        "local_storage_artifacts": _storage_baseline(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="工作区存在改动时返回非零状态。",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    payload = build_baseline(root)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.expanduser()
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
        print(output.resolve())
    else:
        print(serialized, end="")

    if args.require_clean and payload["git"]["dirty_path_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
