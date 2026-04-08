# CortexFlow AI Platform — Claude Instructions

## CHANGELOG Auto-Update Rule
**Every session where code changes are made, update `CHANGELOG.md` with a new version entry.**

- Bump the patch version (e.g. 4.3.0 → 4.3.1) for small fixes, minor version (4.3.x → 4.4.0) for features
- Add the current date (format: `YYYY-MM-DD`)
- List every file changed and what was changed under ### Added / ### Changed / ### Fixed
- Place the new entry at the TOP, above the previous version

## Architecture — Always Remember
- **Graph DB**: SQLite (primary). Neo4j is OPTIONAL fallback at `bolt://localhost:7687`. Always use `get_neo4j_driver()` from `core/database.py` with `timeout=2.0` — never bare `GraphDatabase.driver()`.
- **LLM**: Cohere `command-r7b-12-2024` via `COHERE_API_KEY` in `.env`. Wrapper: `services/phase1_llm.py`.
- **Vector DB**: Qdrant at `localhost:6333`. Collections: `documents`, `phase1_documents`.
- **Auth**: JWT via `app/api/auth_routes.py`. Admin role = full access. User/client = restricted.
- **Ingestion**: Always use async background queue (`services/ingest_queue.py`) — never block the HTTP response for ingestion.
- **Error logging**: All errors go to `logs/error_log.jsonl` via `app/error_logger.py`.

## Code Style
- Never add "not in document" fallbacks to user-facing LLM responses — always be conversational.
- User role gets warm human-like answers. Admin role gets precise technical answers.
- Document exfiltration attempts by non-admins must be blocked and logged as `high` severity SecurityEvent.
- Do not reference Neo4j in the UI — say "SQLite" or "Graph DB (SQLite)".

## Key Files
- `app/main.py` — FastAPI app entry, startup hooks
- `app/api/routes.py` — `/ask`, `/upload`, `/chat/history` endpoints
- `app/api/admin_routes.py` — all `/admin/*` endpoints
- `services/agent_orchestrator.py` — RAG pipeline, caching, LLM call
- `services/phase1_llm.py` — Cohere LLM wrapper with role-aware prompts
- `services/cache_service.py` — TTL-aware in-memory cache (600s default)
- `frontend/src/components/AdminPanel.tsx` — admin dashboard
- `frontend/src/components/ChatInterface.tsx` — chat UI
- `frontend/src/components/DocumentUpload.tsx` — upload page with ETL pipeline view
