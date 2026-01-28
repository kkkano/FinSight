# 2026-01-28 SchemaToolRouter + Clarify Flow

## Summary
- Added SchemaToolRouter for one-shot tool selection with Pydantic validation and template-based clarification.
- Added pending tool state and direct schema tool execution path.
- Synced docs/architecture diagrams and updated env flag documentation.

## Changes
- New schema router: `backend/conversation/schema_router.py`
- Router integration: `backend/conversation/router.py` (USE_SCHEMA_ROUTER)
- Chat handler direct execution: `backend/handlers/chat_handler.py`
- Context pending tool state: `backend/conversation/context.py`
- Clarify flow for schema tools: `backend/conversation/agent.py`
- Unit tests: `tests/unit/test_schema_router.py`
- Docs/README updates + env example update

## Config
- `USE_SCHEMA_ROUTER=false` (opt-in)

## Tests
- `pytest tests/unit/test_schema_router.py -q` (3 passed; PytestDeprecationWarning: asyncio_default_fixture_loop_scope unset)
