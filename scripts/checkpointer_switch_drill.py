#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.checkpointer_cutover import (
    run_checkpointer_cutover_drill,
    write_checkpointer_drill_evidence,
)


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _append_manifest_entry(
    *,
    manifest_path: Path,
    evidence_path: Path,
    result: dict[str, Any],
    postgres_dsn_masked: str,
) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception:
            payload = {}
    else:
        payload = {}

    entries = payload.get('entries')
    if not isinstance(entries, list):
        entries = []

    rel_evidence = str(evidence_path.as_posix())
    entry = {
        'source': f'checkpointer://{postgres_dsn_masked or "postgres"}',
        'exists': True,
        'snapshot': rel_evidence,
        'size': int(evidence_path.stat().st_size),
        'sha256': _sha256_of(evidence_path),
        'type': 'checkpointer_cutover_drill',
        'ok': bool(result.get('ok')),
        'finished_at': result.get('finished_at'),
    }

    entries.append(entry)
    payload['entries'] = entries
    payload['created_at_utc'] = payload.get('created_at_utc') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description='Run Postgres checkpointer cutover/rollback drill')
    parser.add_argument('--sqlite-path', default='data/langgraph/checkpoints.sqlite', help='sqlite checkpointer path')
    parser.add_argument('--postgres-dsn', required=True, help='postgres dsn for checkpointer cutover drill')
    parser.add_argument('--pipeline', action='store_true', help='enable postgres pipeline mode')
    parser.add_argument('--allow-fallback', action='store_true', help='allow memory fallback during drill')
    parser.add_argument(
        '--evidence-path',
        default=f'docs/release_evidence/{datetime.now(timezone.utc).strftime("%Y-%m-%d")}_go_live_drill/checkpointer_switch_drill.json',
        help='output evidence json path',
    )
    parser.add_argument(
        '--manifest-path',
        default=f'docs/release_evidence/{datetime.now(timezone.utc).strftime("%Y-%m-%d")}_go_live_drill/db_snapshot_manifest.json',
        help='snapshot manifest json path',
    )
    parser.add_argument(
        '--allow-failed-drill',
        action='store_true',
        help='return 0 even when drill failed (for local dry-run evidence collection)',
    )
    args = parser.parse_args()

    result = run_checkpointer_cutover_drill(
        sqlite_path=args.sqlite_path,
        postgres_dsn=args.postgres_dsn,
        pipeline=bool(args.pipeline),
        allow_fallback=bool(args.allow_fallback),
    )

    evidence_path = write_checkpointer_drill_evidence(result, args.evidence_path)
    manifest_path = _append_manifest_entry(
        manifest_path=Path(args.manifest_path).expanduser().resolve(),
        evidence_path=evidence_path,
        result=result,
        postgres_dsn_masked=str(result.get('config', {}).get('postgres_dsn') or ''),
    )

    output = {
        'ok': bool(result.get('ok')),
        'evidence_path': str(evidence_path),
        'manifest_path': str(manifest_path),
        'steps': result.get('steps', []),
        'finished_at': result.get('finished_at'),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if result.get('ok'):
        return 0
    return 0 if args.allow_failed_drill else 1


if __name__ == '__main__':
    raise SystemExit(main())
