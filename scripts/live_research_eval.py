"""显式触发真实研究调用，逐项记录正文、质量、持久化及人工验收要求。

凭据只从 FINSIGHT_EVAL_API_KEY 读取；默认串行。脚本不把非空/字数当作内容通过。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

import httpx


ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)


def execute(client, case, session, history):
    started = time.monotonic()
    run_id = 'eval-' + uuid.uuid4().hex
    body = {'query': case['query'], 'session_id': session, 'run_id': run_id,
            'client_user_message_id': uuid.uuid4().hex, 'client_assistant_message_id': uuid.uuid4().hex,
            'history': history[-12:], 'options': {'output_mode': case.get('mode', 'chat')}, 'trace_raw': False}
    events = []
    try:
        with client.stream('POST', '/api/execute', json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    events.append(event)
                    if event.get('type') == 'pipeline_stage' and event.get('status') == 'start':
                        print(json.dumps({'case': case['id'], 'stage': event.get('stage'),
                                          'elapsed': round(time.monotonic() - started, 1)}), flush=True)
        terminal = next((event for event in reversed(events) if event.get('type') in {'done', 'error', 'cancelled'}), {})
        issues = []
        if not terminal: issues.append('missing_terminal')
        if terminal.get('type') == 'done' and not str(terminal.get('response') or '').strip(): issues.append('empty_answer')
        if terminal.get('persistence_status') != 'saved': issues.append('not_saved')
        restored_response = client.get('/api/execute/runs/' + run_id)
        restored_response.raise_for_status()
        restored = restored_response.json()
        if (restored.get('result') or {}).get('response') != terminal.get('response'): issues.append('restored_answer_mismatch')
        if terminal.get('quality_blocked') and (terminal.get('publishable') or terminal.get('archived')):
            issues.append('blocked_but_published')
        if case.get('mode') == 'investment_report' and terminal.get('publishable') and not terminal.get('archived'):
            issues.append('publishable_report_not_archived')
        record = {**case, 'run_id': run_id, 'elapsed_seconds': round(time.monotonic() - started, 2),
                  'answer': terminal.get('response'), 'terminal': terminal, 'contract_errors': issues,
                  'content_review': 'required', 'persistence_verified': not any('saved' in issue or 'mismatch' in issue for issue in issues)}
    except Exception as exc:
        record = {**case, 'run_id': run_id, 'elapsed_seconds': round(time.monotonic() - started, 2),
                  'contract_errors': ['request_exception'], 'exception_type': type(exc).__name__,
                  'http_status': getattr(getattr(exc, 'response', None), 'status_code', None), 'content_review': 'required'}
    if record.get('answer'):
        history.extend([{'role': 'user', 'content': case['query']}, {'role': 'assistant', 'content': record['answer']}])
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--owner', default='internal')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/eval/live_research_questions.json')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    key = os.getenv('FINSIGHT_EVAL_API_KEY', '')
    if not key:
        raise SystemExit('FINSIGHT_EVAL_API_KEY 未配置；未触发任何研究调用。')
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    selected = set(filter(None, args.ids.split(',')))
    if selected:
        if not selected <= {case['id'] for case in cases}:
            raise SystemExit('存在未知 case ID')
        cases = [case for case in cases if case['id'] in selected]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:5]
    histories, results = {}, []
    save(args.out / 'questions.json', {'run': stamp, 'cases': cases,
        'semantic_rag_verified': False, 'note': '真实模型/数据；内容必须人工评审，RAG能力单独验收。'})
    with httpx.Client(base_url=args.url.rstrip('/'), headers={'X-API-Key': key}, timeout=7600, trust_env=False) as client:
        for case in cases:
            session = f"public:{args.owner}:{stamp}-{case.get('thread', case['id'])}"
            print(json.dumps({'case_start': case['id'], 'query': case['query']}, ensure_ascii=False), flush=True)
            record = execute(client, case, session, histories.setdefault(session, []))
            save(args.out / (case['id'] + '.json'), record)
            result = {'id': case['id'], 'seconds': record['elapsed_seconds'], 'contract_errors': record['contract_errors'],
                      'quality': (record.get('terminal', {}).get('quality') or {}).get('state'),
                      'answer_status': record.get('terminal', {}).get('answer_status'), 'content_review': 'required'}
            results.append(result)
            print(json.dumps({'case_done': result}, ensure_ascii=False), flush=True)
    save(args.out / 'summary.json', {'run': stamp, 'results': results})
    if any(row['contract_errors'] for row in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
