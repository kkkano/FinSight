# 2026-02-09 - Config masked secret overwrite fix

## Background

User observed LLM rotation pool frequently failing after opening/saving Settings. Investigation confirmed sensitive keys returned by `GET /api/config` are masked (e.g. `sk-***xyz`), and those masked placeholders could be sent back on save and overwrite real keys in `user_config.json`.

## Root cause

1. Backend redacts secrets in config response by design.
2. Frontend Settings editor treated masked placeholders as normal values and sent them in payload.
3. Backend save flow merged payload directly, so masked placeholders could replace valid API keys.

## Changes

### 1) Backend merge hardening

File: `backend/api/config_router.py`

- Added masked-secret detection (`***` patterns).
- Added preserve logic for legacy single key (`llm_api_key`):
  - if incoming is masked/empty, keep existing secret.
- Added preserve logic for endpoint keys (`llm_endpoints[].api_key`):
  - match by endpoint `name` (fallback by index), keep existing secret when incoming key is masked/empty.

### 2) Frontend submit hardening

File: `frontend/src/components/SettingsModal.tsx`

- Added `isMaskedSecret(...)` helper.
- In endpoint sanitize flow, masked placeholders are not sent as real keys.
- Keep endpoint rows in payload even when key is masked in UI, so backend merge can preserve existing secret.

### 3) Regression tests

File: `backend/tests/test_config_router_secret_merge.py`

- preserve masked single key.
- accept plain new key replacement.
- preserve masked/empty endpoint keys by name/index merge.
- accept plain endpoint key replacement.

## Validation

- `pytest -q backend/tests/test_config_router_secret_merge.py backend/tests/test_llm_rotation.py`
  - result: `15 passed`
- `npm run lint --prefix frontend`
  - result: pass
- `npm run build --prefix frontend`
  - result: failed due to pre-existing unrelated issue:
    - `frontend/src/components/layout/WorkspaceShell.tsx`
    - TS7053: `apiClient['baseUrl']` property not declared in client type

## Impact

- Settings save no longer corrupts live API keys with masked placeholders.
- Rotation pool reliability restored when users open/save config repeatedly.
- Backward compatible for both legacy single-key and multi-endpoint configs.
