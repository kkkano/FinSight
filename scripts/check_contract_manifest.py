# -*- coding: utf-8 -*-
"""
Validate API/Graph contract manifest and print a stable JSON snapshot.

Usage:
  python scripts/check_contract_manifest.py
  python scripts/check_contract_manifest.py --write scripts/contract_manifest.snapshot.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.contracts import contract_manifest


_REQUIRED_KEYS = {
    "chat_request",
    "chat_response",
    "graph_state",
    "sse_event",
    "trace",
    "dashboard_data",
    "report_quality",
}
_SCHEMA_VERSION_PATTERN = re.compile(r"^[a-z0-9_.-]+\.v\d+$")


def _validate_manifest(payload: dict[str, str]) -> list[str]:
    errors: list[str] = []
    missing = sorted(_REQUIRED_KEYS - set(payload.keys()))
    if missing:
        errors.append(f"missing keys: {missing}")

    for key, value in payload.items():
        text = str(value or "").strip()
        if not text:
            errors.append(f"{key}: empty schema version")
            continue
        if not _SCHEMA_VERSION_PATTERN.fullmatch(text):
            errors.append(f"{key}: invalid schema version format `{text}`")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=str, default="")
    args = parser.parse_args()

    manifest = contract_manifest()
    errors = _validate_manifest(manifest)
    if errors:
        for item in errors:
            print(f"[contract-check] {item}")
        return 1

    serialized = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)

    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
        print(f"[contract-check] snapshot written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
