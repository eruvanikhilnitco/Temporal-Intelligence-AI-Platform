# CortexFlow AI — Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [4.1.0] — 2026-04-07

### Added
- **Structured error logging system** (`app/error_logger.py`)
  - JSON Lines log at `logs/error_log.jsonl` + plain-text mirror at `logs/error_log.txt`
  - FastAPI middleware captures all unhandled exceptions and HTTP 5xx responses automatically
  - Every entry includes: timestamp, level, source, message, exception type, full traceback, request_id, path, user
  - Admin endpoints: `GET /admin/errors`, `GET /admin/errors/stats`, `DELETE /admin/errors`
  - Manual helpers: `log_error()`, `log_warning()`, `log_critical()` callable from any service
- **GUARDRAILS.md** — comprehensive documentation of all safety and access control layers
- **CHANGELOG.md** — this file
- **README.md** — fully updated with Neo4j setup, new features, API reference, and troubleshooting table
- **`Error log.py`** — placeholder replaced by the full `app/error_logger.py` implementation

### Changed
- `app/services/rag_service.py` — RAG query failures and ingest errors now call `log_error()` instead of only `logger.error()`
- `app/main.py` — startup DB failure now calls `log_critical()` for persistence in the error log
- Neo4j port corrected in `core/config.py`: `7689` → `7687` (was unreachable before)

---

## [4.0.0] — 2026-04-06

### Added
- **Neo4j integration** (`services/graph_service.py` rewritten with dual-backend architecture)
  - Primary: Neo4j 5.18 via official Python driver (`bolt://localhost:7687`)
  - Fallback: SQLite — automatic, zero-downtime switch if Neo4j is unreachable
  - Open/Closed: `_Neo4jBackend` and `_SQLiteBackend` both implement `_GraphBackend` — add new backends without touching existing code
- **`docker-compose.yml`** — Neo4j 5.18-community container with persistent volumes
- **Enhanced Orchestrator** (`services/enhanced_orchestrator.py`)
  - `EnhancedAgentOrchestrator` subclasses `AgentOrchestrator` (Open/Closed Principle)
  - `DocumentLineReaderTool` — verbatim line/document retrieval, zero LLM involvement
  - `SourceAnnotatedSearchTool` — per-file filtered Qdrant search with source attribution
  - `CrossDocumentTool` — detects compare/contrast queries, retrieves from each doc independently
  - `_node_classify` calls `parse_query()` unconditionally — no intent gate blocking keywords
- **Document Reader** (`services/document_reader.py`)
  - Fuzzy filename matching via word-overlap scoring (no exact match required)
  - 6 ordinal line-number patterns: "line 40", "40th line", "line:40", "fortieth line", etc.
  - Broad DOC_READ_INTENT regex: retrieve, extract, pull, return, bring, find, tell, access, look at, view, open, read, show, display, give, fetch, get
- **Metadata Extractor** (`services/metadata_extractor.py`)
  - Auto domain classification: legal, finance, hr, medical, technical, operations, general
  - Auto doc_type detection: contract, policy, report, invoice, manual, etc.
  - Auto sensitivity: high / medium / low — based on keyword scoring, entity counts, structural signals
  - No domain names hardcoded — extend by adding entries to `DOMAIN_PROFILES`
- **Folder Upload** (`app/api/routes.py` + `frontend/src/components/DocumentUpload.tsx`)
  - `POST /upload/batch` — accepts multiple files with relative paths preserved
  - Frontend "Folder Upload" tab using `webkitdirectory` browser API
  - Nested subfolder support; per-file status display
- **Document Access Control** (`app/api/admin_routes.py`)
  - `PUT /admin/document/access` — update access_roles for all chunks of a document in Qdrant
  - `GET /admin/document/access` — inspect current access for a document
  - `GET /admin/document/read` — verbatim document read via API (line, range, or full)
  - `GET /admin/document/list` — list all uploaded documents with size and metadata
- **Cross-document graph links** (`services/graph_service.py`)
  - `create_cross_document_links()` — finds SHARES_ENTITY_WITH relationships at ingest
  - `get_document_neighbors()` — used by CrossDocumentTool for query routing
  - `store_document_metadata()` — domain/doc_type/sensitivity stored as graph nodes
- **SharePoint ingestion via Office365-REST-Python-Client** (`app/api/admin_routes.py`)
  - `UserCredential` auth replacing basic-auth `requests` (works with SharePoint Online / O365)
  - Recursive folder traversal; skips system folders (Forms, _private, Attachments)
  - Correct download API: `ctx.web.get_file_by_server_relative_url(url).download(fh).execute_query()`

### Fixed
- "Retrieve 40th line" returning "Not found" — `_node_classify` now calls `parse_query()` before any intent gate check
- SharePoint ingesting 0 files — wrong download API replaced with correct chained call
- `NameError: name 'Path' is not defined` in `CrossDocumentTool.find_mentioned_docs`
- `find_mentioned_docs` using filesystem filenames instead of Qdrant-stored names (folder-upload prefix mismatch)
- Newly ingested documents defaulting to `["public","user","admin"]` — changed to `["admin"]` secure-by-default

### Changed
- `Phase1RAG.query()` now delegates to `query_with_sources()` internally — backward-compatible
- `query_with_sources()` returns `[{text, file_name, score, domain}]` per chunk
- `_get_orchestrator()` in `rag_service.py` now prefers `EnhancedAgentOrchestrator` with graceful fallback

---

## [3.0.0] — 2026-03-15

### Added
- Agent Orchestrator (`services/agent_orchestrator.py`) — LangGraph-style decision pipeline
- Semantic cache — avoids redundant LLM calls for repeated queries
- Cross-encoder reranker — improves retrieval precision
- Query classifier — routes to fact / summary / graph / comparison query types
- ChatGPT-style conversation sidebar with persistent chat state across page navigation
- SQLite knowledge graph tables (`graph_nodes`, `graph_edges`) — no Neo4j required at this stage
- Admin Panel tabs: Monitoring, Chunks viewer (grouped by document), Storage Info
- SharePoint REST API ingestion (basic-auth — later replaced in v4.0)

### Fixed
- Frontend undefined crashes in Graph / Analytics / Admin pages on first load
- RAG service not pre-warming at startup (first request timeout)
- Missing proxy routes for `/admin`, `/chat`, `/feedback` in Vite config

---

## [2.0.0] — 2026-02-28

### Added
- Knowledge Graph Phase 3: entity extraction (contracts, dates, amounts, organizations) + NER
- Graph RAG: hybrid vector + graph retrieval
- Graph visualisation: force-directed node graph with zoom, search, type filters
- Analytics page: daily trend chart, hourly distribution, cache stats
- Rule Engine: admin CRUD for content guardrail rules
- Security Events log with severity filter and resolve actions
- User management: block/unblock, role assignment

### Changed
- Embedding model upgraded to BAAI/bge-large-en-v1.5 (1024-dim, from 384-dim)
- Qdrant collection migrated to 1024-dim vectors

---

## [1.0.0] — 2026-01-20

### Added
- Phase 1 RAG: Qdrant vector store + BAAI embeddings + Cohere LLM
- FastAPI backend with JWT authentication (admin / user roles)
- React 18 + TypeScript + Vite frontend
- Document upload: PDF, XML, TXT, DOCX, JSON, CSV, HTML
- Phase1Pipeline: parse → chunk → embed → store
- Basic chat interface with source citations
- Admin panel skeleton
- PostgreSQL → SQLite fallback database
- Default user seeding (`admin@test.com`, `user@test.com`)
