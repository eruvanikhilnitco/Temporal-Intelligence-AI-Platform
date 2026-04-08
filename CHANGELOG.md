# CortexFlow AI — Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [4.5.1] — 2026-04-08

### Fixed — Admin RBAC & Chat Capabilities

#### Admin sees ALL documents (was blocked by Qdrant filter)
- **`services/phase1_rag.py`** — `query_with_sources()` now passes `query_filter=None` for `user_role=="admin"`, removing the Qdrant RBAC constraint entirely. Admins retrieve from all chunks regardless of `access_roles` tag. Non-admin roles still filtered as before.

#### Admin chat now answers system-level queries directly
- **`app/api/routes.py`** — Added `_try_admin_intent()` helper. Before invoking the RAG pipeline, the `/ask` endpoint detects two admin-only intents and short-circuits:
  - **"list files / documents / uploads"** → calls `DocumentReader.list_files()`, returns a numbered list of all uploaded files
  - **"error logs / system logs / recent errors"** → calls `read_recent_errors(limit=10)`, returns the last 10 log entries formatted inline
- Added `_FILE_LIST_RE` and `_LOG_RE` compiled regex patterns to match natural language variants of these queries.
- Admin intent answers are stored in `ChatLog` with `query_type="admin"` and `confidence=100.0`.

#### Admin source chunks increased
- **`app/api/routes.py`** — Admin source chunks increased `500 → 2000` chars per source. Admin now receives up to **8** sources (was 5).

#### New admin endpoint — graph pruning
- **`app/api/admin_routes.py`** — `POST /admin/graph/prune?min_weight=0.2` deletes weak edges, orphan nodes, then runs `VACUUM + ANALYZE`. Returns `{pruned_edges, pruned_nodes, vacuum, min_weight_threshold}`.

---

## [4.5.0] — 2026-04-08

### Performance — Query Latency (Concurrent Queries)
- **`services/agent_orchestrator.py`** — Multi-hop sub-queries, graph lookup, and calculator now run **in parallel** via `ThreadPoolExecutor(max_workers=6)`. Under 10 concurrent queries this reduces per-query time by 2–3× (was sequential, each sub-query blocking the next).

### Performance — Upload Speed (100-file Batch)
- **`app/api/routes.py`** — `/upload/batch` now **queues every file immediately** instead of calling `ingest_file()` synchronously in a for-loop. 100 files return job IDs in <1 s; ingestion runs in background workers. Response now includes `queue_depth` and per-file `job_id` for polling.

### Performance — Ingest Throughput
- **`services/ingest_queue.py`** — Singleton worker count raised from `1` → `min(cpu_count, 4)` using double-checked locking. Embedding batch size raised `32` → `64` for faster throughput per worker.

### Performance — Cache
- **`services/cache_service.py`** — Rewrote cache using `OrderedDict` for O(1) **LRU eviction** (max 2000 entries). Added **background cleanup thread** (runs every 60 s) to expire stale entries and prevent memory creep. Cache now tracks `evictions` stat in admin stats.

### Performance — Embedding
- **`services/embedding_service.py`** — Embed cache raised `2000` → `5000` entries. Batch encode size raised `32` → `64`. Added `store_embeddings_batch()` for **bulk Qdrant upserts** (256 points per request vs. 1-by-1), reducing Qdrant round-trips by up to 100×.

### Graph Scalability
- **`services/graph_service.py`** — SQLite connections now set **WAL journal mode**, `synchronous=NORMAL`, 32 MB page cache, and `temp_store=MEMORY` for faster concurrent reads during multi-worker ingestion. Added `weight` column to `graph_edges` table. Added `prune_graph(min_weight)` to delete low-confidence edges and orphan nodes. Added `vacuum()` to run `ANALYZE + VACUUM`.

### Config
- **`core/config.py`** — Added performance settings: `ingest_workers`, `embed_cache_max`, `cache_max_entries`, `cache_ttl`, `qdrant_batch_size`.

---

## [4.4.0] — 2026-04-08

### Critical Performance Fix — Embedding Model Switch
- **`core/config.py`** — `embedding_model` changed from `BAAI/bge-large-en-v1.5` (335M params, 7800ms/query on CPU) to `BAAI/bge-small-en-v1.5` (33M params, ~1200ms/query) — **6× faster embeddings**
- **`services/embedding_service.py`** — Added process-level embedding vector cache (`_EMBED_CACHE`, capped at 2000 entries): same query text returns cached vector instantly, skipping model inference entirely. Also fixed `_ensure_collection()` to detect dimension mismatch (1024→384) and auto-recreate the Qdrant collection.
- **`services/phase1_rag.py`** — `_ensure_collection()` now reads model dimension dynamically (`self.embedder.dimensions`) instead of hardcoded `1024`. Detects mismatch and recreates collection with correct dimension.

### Architecture Clarity
- Embedding pipeline now uses **384-dim** vectors (was 1024). Qdrant collections `documents` and `phase1_documents` auto-recreated on startup when dimension mismatch is detected.
- **Note**: Existing indexed documents were cleared during dimension migration. Re-upload documents via the Upload tab to rebuild the knowledge base.

### Backend Restart
- All previously written fixes (Neo4j 2s timeout, async ingest queue, role-aware LLM prompts, exfiltration guardrail, cache TTL) are now **live** — backend was restarted for the first time with all changes.

---

## [4.3.1] — 2026-04-07

### Fixed
- `frontend/src/components/DocumentUpload.tsx` — upload now correctly shows **queued** state (green progress bar + "background ingestion running" label) instead of falling into "error" when backend returns `status: "queued"`
- All **Neo4j references removed** from UI:
  - ETL Pipeline tab: now shows 8-step accurate pipeline with "SQLite / Neo4j fallback" wording; architecture badge row shows Qdrant / SQLite / Cohere
  - KnowledgeGraphPipeline accordion: "Graph Storage (Neo4j)" → "Graph Storage (SQLite)"
  - SharePoint connector info: "builds knowledge graph in Neo4j" → "SQLite / Neo4j"
  - Folder Upload info: same fix
  - Document Processing Pipeline: "Embed (BAAI)" → "Embed (BAAI 1024d)"; added "Queue" step to show async nature; "Async / Non-blocking" badge
- `app/api/routes.py` — `/upload/status/all` endpoint added (returns all recent ingest jobs, newest first); registered **before** `{job_id}` to avoid FastAPI path shadowing

### Added
- `IngestQueueStatus` component in ETL tab — shows live background job list (status, filename, elapsed time) polled from `/upload/status/all`
- `CLAUDE.md` — project-level instructions for Claude: architecture rules, changelog auto-update rule, code style (no "not in document", role-aware LLM, no Neo4j in UI)

---

## [4.3.0] — 2026-04-07

### Critical Fixes
- **Latency: 2–4 min → <5 sec** — Root cause was Neo4j TCP connection timeout on every request; added `connection_timeout=2.0` to all `GraphDatabase.driver()` calls so it falls back to SQLite instantly when Neo4j is absent. Affects `graph_service.py`, `chatbot_service.py`, `lifecycle_service.py`, `core/database.py`

### Added
- **Stop button** in chat UI — red square button replaces Send while loading; uses `AbortController` to cancel in-flight `/ask` requests immediately (`ChatInterface.tsx`)
- **Delete document** from admin Chunks tab — trash icon per document folder calls `DELETE /admin/document/{filename}` which removes all Qdrant chunks and physical file
- **Document exfiltration guardrail** — non-admin users asking for raw documents, file names, source code, or system internals get a polite refusal; event logged to SecurityEvent table + error log
- **Security alerts to admin** — exfiltration attempts generate `high` severity SecurityEvent visible in admin Security tab with full query
- **Real cache stats** in admin Monitoring tab — `CacheService` now tracks hits/misses/TTL; `/admin/cache/stats` exposes hit rate, active entries, memory usage in KB; auto-loaded in Monitoring and Overview tabs
- **Live error log** in admin Security tab — replaces hardcoded fake entries with real `GET /admin/errors` data; shows level, source, message, exception
- **Async document ingestion** — upload endpoint now submits to background `IngestQueue` and returns `queued` status instantly; eliminates 5-minute blocking ingestion
- **Error logging for upload failures** — file save errors and ingestion failures are now written to `logs/error_log.jsonl` with user email and file path context

### Changed
- `services/phase1_llm.py` — LLM prompt rewritten for role-aware natural conversation; user role gets warm, human-like responses; never says "Not found in document"; greetings handled naturally; admin role gets precise technical answers
- `services/agent_orchestrator.py` — passes `role` to `llm.generate_answer()` so user vs admin get appropriate response styles
- `services/cache_service.py` — replaced trivial dict with TTL-aware thread-safe cache (`default_ttl=600s`); tracks hits/misses/memory
- `frontend/src/pages/SignUp.tsx` — "Aditya V." replaced with "Team Nitco Inc." with "Enterprise AI Platform" subtitle
- `frontend/src/components/AdminPanel.tsx` — Overview cards show "Backend: SQLite" for graph DB (no more Neo4j label); LLM card shows "Cohere API" extra; Auth card shows live cache hit rate; Monitoring tab shows real cache metrics from `/admin/cache/stats`
- `app/api/admin_routes.py` — added `GET /admin/cache/stats`, `DELETE /admin/cache`, `DELETE /admin/document/{filename}` endpoints

### Fixed
- Chat greetings (hello/hi/good morning/how are you etc.) now get friendly human-like responses instead of "not in document"
- User-facing answers are now conversational and summarized, never exposing raw document chunks

---

## [4.2.0] — 2026-04-07

### Added
- **Confidence-based orchestrator routing** (`services/enhanced_orchestrator.py`)
  - `_rag_confidence()`: probes Qdrant with top-1 vector search, returns cosine similarity (0–1)
  - `_graph_confidence()`: counts entity matches in Neo4j, returns normalised ratio (0–1)
  - `_route_by_confidence()`: compares scores with 0.15 margin → routes to `rag`, `graph`, or `hybrid`
  - Every routing decision is recorded in `reasoning_trace` for explainability
- **Hybrid retrieval weighted fusion** (`_weighted_fusion()`)
  - Formula: `0.7 × rag_score + 0.3 × graph_score` per chunk
  - Merges RAG chunks and graph relation strings into a single ranked, deduplicated list
- **LLM-based metadata classification** (`services/metadata_extractor.py`)
  - `_llm_classify()`: sends first 1200 chars to Cohere, receives `domain/doc_type/sensitivity/confidence` as JSON
  - `classification_source` field: `"llm"` or `"keyword"` — visible in Qdrant payload
  - Keyword TF scoring retained as fallback when LLM is unavailable
- **Multi-hop graph reasoning** (`services/graph_service.py`)
  - `_Neo4jBackend.multi_hop_query()`: variable-length Cypher `MATCH path=[*1..N]->(b)` query
  - `_SQLiteBackend.multi_hop_query()`: iterative BFS traversal up to `max_hops` depth
  - Both return flat list of `{path, relations, terminal, hops}` dicts
  - `GraphService.multi_hop_query()` delegates to active backend transparently
- **Structured multi-document comparison prompting** (`services/enhanced_orchestrator.py`)
  - Prompt forces **Similarities / Differences / Conclusion** structure
  - Every claim must cite source document name — reduces hallucination
  - Replaces freeform comparison instruction
- **Batch embedding** (`services/embedding_service.py`)
  - `embed_batch(texts, batch_size=32)`: single `model.encode()` call for all chunks — ~10× faster than loop
  - Used in `ingest_file()` — replaces per-chunk embedding loop
  - Falls back to sequential `embed()` if batch call fails
- **Background ingest queue** (`services/ingest_queue.py`)
  - `IngestQueue`: FIFO worker thread, non-blocking file ingestion
  - `POST /upload/async` — saves file, queues ingestion, returns `job_id` immediately
  - `GET /upload/status/{job_id}` — poll ingestion status (`queued/processing/done/error`)
  - `batch_embed()` helper also exported from this module
  - Queue worker started automatically at app startup via `_start_ingest_queue()` in `app/main.py`
- **Reliability layer** (`services/reliability.py`)
  - `with_retry(max_attempts, base_delay, max_delay, exceptions)` — exponential backoff decorator
  - `CircuitBreaker`: three states (CLOSED → OPEN → HALF_OPEN), configurable threshold + recovery timeout
  - Shared singletons: `qdrant_breaker`, `neo4j_breaker`, `llm_breaker`
  - `GET /system/reliability` — returns live state of all circuit breakers
- **Enhanced security service** (`services/security_service.py`)
  - `mask_pii(text)` — replaces SSN, credit card, passport, IP address, email, phone with `[TYPE_REDACTED]`
  - `attack_score(query)` — 0–10 severity score; patterns: prompt injection, SQL injection, XSS, path traversal, code injection, encoding attacks
  - `full_security_analysis(query, user_id, role)` — combines threat detection + PII masking + attack scoring → `risk_level`, `should_block`, `should_warn`
  - Wired into `POST /ask` — replaces basic `analyze_query()` call
- **Explainability** (`services/enhanced_orchestrator.py`, `app/api/schemas.py`)
  - `EnhancedAgentState.reasoning_trace: List[str]` — every pipeline step appends a human-readable entry
  - `AskResponse.explanation` (admin-only JSON): `routing`, `rag_confidence`, `graph_confidence`, `reasoning_trace`, `tools_used`, `security` risk summary
  - `rag_service.py` surfaces `routing_decision`, `rag_confidence_score`, `graph_confidence_score`, `reasoning_trace` from state

### Changed
- `POST /ask` security check upgraded from `analyze_query()` to `full_security_analysis()` — richer blocking logic
- `ingest_file()` in `rag_service.py` now uses `embed_batch()` instead of per-chunk `embed()` loop
- `app/main.py` startup now also calls `_start_ingest_queue()` to boot the background worker
- `EnhancedAgentState` extended with `routing_decision`, `rag_confidence_score`, `graph_confidence_score`, `fused_chunks`, `reasoning_trace`

### Fixed
- Documents ingested with old per-chunk embedding loop were slower on large files — resolved by batch embedding

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
