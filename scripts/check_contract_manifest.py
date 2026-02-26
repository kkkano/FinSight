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

from backend.contracts import contract_manifest, report_quality_reason_codes_manifest


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
_REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


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


def _validate_reason_codes(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    schema_version = str(payload.get("schema_version") or "").strip()
    if not schema_version:
        errors.append("reason-codes: empty schema version")
    elif not _SCHEMA_VERSION_PATTERN.fullmatch(schema_version):
        errors.append(f"reason-codes: invalid schema version format `{schema_version}`")

    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, list) or not raw_codes:
        errors.append("reason-codes: codes must be a non-empty list")
        return errors

    seen: set[str] = set()
    for code in raw_codes:
        text = str(code or "").strip()
        if not _REASON_CODE_PATTERN.fullmatch(text):
            errors.append(f"reason-codes: invalid code `{text}`")
            continue
        if text in seen:
            errors.append(f"reason-codes: duplicate code `{text}`")
            continue
        seen.add(text)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=str, default="")
    args = parser.parse_args()

    manifest = contract_manifest()
    errors = _validate_manifest(manifest)
    reason_payload = report_quality_reason_codes_manifest()
    errors.extend(_validate_reason_codes(reason_payload))
    if errors:
        for item in errors:
            print(f"[contract-check] {item}")
        return 1

    snapshot_payload = {
        "contracts": manifest,
        "report_quality_reason_codes": reason_payload,
    }
    serialized = json.dumps(snapshot_payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)

    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
        print(f"[contract-check] snapshot written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
