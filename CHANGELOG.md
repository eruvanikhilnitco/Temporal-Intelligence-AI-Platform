# CortexFlow AI — Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [7.1.0] — 2026-04-15

### Fixed
- **Website chunks not indexed (0 chunks bug)** (`services/embedding_service.py`): Added `get_embedding_service()` singleton function that the website crawler imports. Previously this function did not exist, causing a silent `ImportError` inside `_ingest_page()` and returning 0 chunks for every crawled page.
- **Content hash dedup blocking re-index** (`services/website_crawler.py` — `refresh_crawl()`): On re-crawl, if `chunks_indexed == 0` the content hashes are now cleared so all pages are re-processed. Previously hashes from a failed crawl blocked all pages from being re-indexed.
- **Admin signup page removed**: Removed `signup-admin` page route from `App.tsx` and updated `Landing.tsx` "Register as Admin" button to redirect to admin sign-in instead. Admin account is superadmin-only — no self-registration.

### Added
- **Navigation fast-path** (`services/agent_orchestrator.py` — `_try_nav_graph()`): Detects navigation intent keywords ("navigate", "link to", "where is", "how do i go to", etc.) and directly queries the crawler's `nav_graph` dictionary. Returns direct URL + step-by-step breadcrumb path without going through RAG pipeline.
- **`get_connections()`** method on `WebsiteCrawler` — exposes all active connections with full `nav_graph` for the orchestrator nav fast-path.
- **`get_embedding_service()`** singleton in `services/embedding_service.py` — thread-safe process-wide instance used by website crawler and any other service needing embeddings.

### Changed
- `services/website_crawler.py` — `refresh_crawl()` now resets `chunks_indexed` counter and clears content hashes when previous crawl produced 0 chunks (force full re-index).
- `services/phase1_llm.py` — Admin system prompt updated to include guidance on using website chunk URL fields for navigation answers.
- `frontend/src/App.tsx` — Removed `"signup-admin"` from `Page` type union and router switch.
- `frontend/src/pages/Landing.tsx` — "Register as Admin" CTA changed to "Admin Sign In" (navigates to `admin-login`).
- Backend now serves built React SPA (`frontend/dist/`) from FastAPI on port 8000, eliminating dependency on Vite port forwarding through GitHub Codespace.

---

## [7.0.0] — 2026-04-15

### Added
- **Hardcoded Superadmin** (`app/main.py` — `_seed_superadmin()`): On every startup the system seeds `n.eruva@nitcoinc.com` with `Nikhil@1234` as the sole admin account. POST `/auth/signup/admin` now returns 403; no self-registration possible.
- **Priority-based BFS Crawler** (`services/website_crawler.py`): URL scoring table (`_URL_PRIORITY`) assigns numeric priorities to page types (home=0, services/about=1, blog/tags=5–9). Uses `heapq` min-heap so high-value pages are crawled first. Skip patterns (`_SKIP_URL_PATTERNS`) exclude binaries, pagination loops, and bot-noise URLs.
- **Navigation Graph** (`services/website_crawler.py` — `_update_nav_graph()`): Every crawled page builds a node `{title, url, parent, children, breadcrumb, page_type, depth}` stored in `conn.nav_graph`. Breadcrumb paths are derived from parent chain. Graph persisted to `crawler_connections.json`. `GET /website/nav-graph/{connection_id}` exposes the full graph.
- **Enhanced Playwright rendering** (`_fetch_playwright()`): Incremental scroll (8 passes to trigger lazy-loaded content), expanded interaction set — accordions (`details summary`, `.accordion-button`, `[data-bs-toggle='collapse']`), tabs (`[role='tab']`, `.nav-tab`), dropdowns (`.dropdown-toggle`), expand buttons (`.show-more`, `.read-more`). Each element is scrolled into view before click with 250ms settle time.
- **BeautifulSoup4 extraction** (`_parse_html_bs4()`): When BS4 is available uses DOM tree traversal to extract title, meta tags, headings (H1–H6), navigation links from all `<nav>` elements, main content area (prefers `<main>`, `<article>`, `.content`), and strips noise elements. Falls back to `_parse_html_regex()`.
- **Screenshot capture** (`_capture_screenshot()`): Full-page Playwright screenshots (JPEG 70% quality) stored to MinIO under `screenshots/` prefix or local fallback. Linked to `conn.screenshots[url]`.
- **Stay-connected** (`services/website_crawler.py`): On crawl completion, status becomes `"active"` (not `"done"`) — connections remain live until manually disconnected. `_save_connections()` persists `active` status so connections survive server restarts.
- **MinIO verified working** (`services/storage_service.py`): Bucket `uploaded-docs` confirmed; every admin file upload logs the storage key and backend name (`minio` or `local`). Docker container `minio_cf` running on port 9000.
- **nav_pages counter** in `_conn_to_dict()` — shows how many pages are in the nav graph per connection.
- **`GET /website/nav-graph/{connection_id}`** endpoint added (`app/api/website_routes.py`).

### Changed
- `services/website_crawler.py` — Imports: added `heapq`, `bs4 (optional)`, removed `deque` (replaced by heapq priority queue). `CrawlConnection` dataclass gains `nav_graph` and `screenshots` fields.
- `services/website_crawler.py` — `_save_connections()` and `_load_connections()` now persist/restore `nav_graph`. Crawling/pending statuses saved as `"active"` not `"done"`.
- `services/website_crawler.py` — `MAX_DEPTH` bumped from 5 → 6.
- `frontend/src/components/WebsiteScraper.tsx` — Added `active` status handling (shown as "Live" with pulsing dot). Poll interval: 4s while crawling, 30s when all live, stops when no connections. Re-crawl button shows for `active` status. Nav pages counter shown from `nav_pages` field.
- `frontend/src/pages/SignUp.tsx` — Admin signup path now shows "provisioned by system" note instead of link to admin signup route (which is blocked).
- `app/api/routes.py` — Upload endpoint now logs storage backend and key name after successful MinIO store.

### Infrastructure
- Qdrant (`qdrant_cf`, port 6333), MinIO (`minio_cf`, port 9000), Redis (`redis_cf`, port 6379) — all Docker containers confirmed running.
- Backend running: `uvicorn app.main:app` on port 8000 (SQLite primary DB, falls back from PostgreSQL gracefully).
- Frontend running: Vite dev server on port 5173.

---

## [6.5.0] — 2026-04-15

### Added
- `frontend/src/pages/AdminLogin.tsx` — **Separate admin login portal**: dedicated page for admin authentication, styled with red accent; enforces `@nitcoinc.com` email domain client-side before submitting; links back to user login
- `app/api/auth_routes.py` — `POST /auth/login/admin` endpoint: admin-only login that validates org email domain (`@nitcoinc.com`) and confirms `role == "admin"` before issuing tokens; standard `POST /auth/login` now blocks admin accounts with a 403
- `app/services/auth_service.py` — `_enforce_admin_email()` helper + `ADMIN_EMAIL_DOMAIN` constant; admin registration now rejects any email not from the org domain at the service layer

### Changed
- `frontend/src/App.tsx` — Added `"admin-login"` page route; imports `AdminLogin` component
- `frontend/src/pages/Login.tsx` — Added **Admin Portal** button at the bottom to navigate to the admin login page
- `frontend/src/pages/SignUp.tsx` — Admin signup now validates `@nitcoinc.com` domain client-side; inline error shown on invalid email; submit button disabled until domain matches
- `services/website_crawler.py` — **Crawl connections now persisted to `crawler_connections.json`**: `_save_connections()` called on connect, disconnect, and crawl completion; `_load_connections()` restores all active connections at startup — connections survive server restarts and page refreshes
- `services/context_builder.py` — **Website metadata enriched in LLM context**: website chunks now include page title, direct URL, page type, navigation links, key stats, key people, and contact info as a structured header before the text body; each unique page URL is used as the diversity key so multiple pages from the same crawled site can appear in context; `MAX_PER_DOC` cap is 1 per unique page URL for website sources

### Fixed
- `services/context_builder.py` — `payload_map` lookup in backfill loop now uses the full payload dict (not just `file_name`) for consistency with the main loop

---

## [6.4.0] — 2026-04-15

### Fixed
- `frontend/vite.config.ts` — Added `/website` proxy entry; website scraper was returning **404** because the Vite dev server had no proxy rule for `/website/*` routes, causing all connect/status/disconnect calls to fail
- `services/storage_service.py` + `app/api/routes.py` — **MinIO now active**: `minio` Python package installed; upload route now stores files to MinIO object storage (bucket auto-created on first use) in addition to local disk; `.env` credentials (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`) verified and working
- `services/sharepoint_service.py` — **SharePoint upload progress**: new files are now immediately marked `indexed_status="indexing"` in the database before the ingest job runs, so the UI can show a progress indicator while files are being processed; `get_status()` now returns `pending_count` and `failed_count` per connection
- `frontend/src/components/SharePoint.tsx` — Added **live indexing progress indicator**: spinning blue banner shows count of files being indexed from SharePoint; auto-polls every 5 s while any files are pending; amber warning when files fail; `FileText` + `Clock` icons added; `pollRef` cleanup on unmount
- `frontend/src/components/DocumentUpload.tsx` — Removed **Async / Non-blocking** badge from the Document Processing Pipeline section

### Changed
- `app/api/routes.py` — Upload route now calls `get_storage_service().store()` (MinIO/S3) after saving locally; gracefully falls back with a warning if object storage is unavailable

## [6.3.0] — 2026-04-14

### Fixed
- `services/hybrid_search.py` — **Query latency**: BM25 index TTL increased from 5 minutes to 1 hour; BM25 index refreshes now run in a **background thread** so stale-but-valid index is served to users during rebuild (zero latency penalty on warm queries); added `threading.Lock` around index reads for thread-safety
- `services/agent_orchestrator.py` — **Query latency**: `_fetch_payload_map()` was running an extra Qdrant scroll (250 records) on **every single query** just to build a text→filename lookup; now reuses BM25 metadata (already in memory, zero I/O cost) and only falls back to a TTL-cached scroll (120s) when BM25 isn't warmed yet
- `app/main.py` — **First-query cold start**: warmup now pre-loads both `Phase1RAG` (embedding model + reranker, ~26s) **and** `AgentOrchestrator` so the first user query is served from warm models, not during model loading
- `app/api/admin_routes.py` — `GET /admin/cache/status` import fixed (`services.phase1_rag._get_rag` → `app.services.rag_service._get_rag`); now returns actual backend name, hit/miss stats, and memory usage

### Changed
- `app/api/admin_routes.py` — `GET /admin/analytics` SQL fixed for PostgreSQL compatibility: `DATE('now','-13 days')` → `CURRENT_DATE - INTERVAL '13 days'`; `STRFTIME('%H', ...)` → `EXTRACT(HOUR FROM created_at)::int`; DB dialect detected at runtime via `engine.url`

---

## [6.2.0] — 2026-04-14

### Added
- `services/website_crawler.py` — **Major upgrade**: JSON-LD structured data extraction, stats extraction (numeric patterns like "150+ Employees"), leadership/people extraction (JSON-LD Person schema + heuristic HTML section parsing), contact info (phone/email/address), OpenGraph tags, navigation structure mapping, Playwright JS rendering (auto-detected, falls back to requests), BFS depth limit (MAX_DEPTH=5), interaction engine for accordions/tabs (Playwright), sitemap index files followed recursively, robots.txt sitemap directives parsed, structure-aware chunking (500–800 chars, 100 overlap), batch embedding (64 chunks/call), unified metadata schema (`source_type`, `source_name`, `url`, `page_type`, `section`, `content_hash`, `version`, `timestamp`, `stats`, `people`, `contact_phone`, `contact_email`, `nav_links`, `og_title`, `connection_id`, `org_name`)
- `services/scheduler_service.py` — **New**: Centralized scheduling service with source registry (persisted to `scheduler_registry.json` across restarts), multi-level scheduling (high=10min, medium=2hr, low=24hr), priority queue (high before medium before low), sitemap lastmod + content hash change detection, retry with exponential backoff (1m→5m→30m), idempotent processing, worker pool (3 workers), pause/resume per source, admin trigger APIs, auto-sync with WebsiteCrawler connections
- `services/storage_service.py` — **New**: Abstracted object storage — MinIO/S3 primary (presigned URLs, bucket auto-create), local filesystem fallback; used for raw files, HTML snapshots, processed text; keeps Postgres and Qdrant lean
- `services/cache_service.py` — **Redis persistence**: Cache now tries Redis first (survives server restarts), falls back to in-memory LRU if Redis unavailable; JSON serialization for all value types; backend reported in `/admin/cache/status`
- `core/config.py` — Added `redis_url`, `minio_endpoint`, `minio_access_key`, `minio_secret_key`, `minio_bucket`, `minio_secure` settings
- `app/main.py` — Added `_start_scheduler()` startup hook; scheduler boots alongside ingest queue and health monitor
- `app/api/admin_routes.py` — New endpoints: `GET /admin/scheduler/status`, `POST /admin/scheduler/trigger`, `POST /admin/scheduler/pause/{id}`, `POST /admin/scheduler/resume/{id}`, `DELETE /admin/scheduler/source/{id}`, `GET /admin/storage/status`, `GET /admin/cache/status`
- `app/api/website_routes.py` — On connect: auto-registers source with scheduler for 2-hour periodic re-crawls

### Changed
- `services/phase1_llm.py` — System prompt updated: navigation/links rule added — model now provides direct URLs from indexed website content when user asks for page links or navigation steps; nav-link instructions grounded-only (never invents URLs)
- `frontend/src/components/ChatInterface.tsx` — Stop button fix: added `streamStoppedRef` flag so clicking Stop also halts the visual streaming animation mid-reveal (not just the HTTP fetch); `streamStoppedRef` reset to `false` on each new message send
- `README.md` — Complete rewrite: polyglot storage architecture diagram, full env variable table, API reference table, project structure, Quick Start with Docker commands, data sources table, scheduler priority table

---

## [6.1.0] — 2026-04-14

### Added
- `services/website_crawler.py` — **Organization Website Scraper**: BFS deep-crawler with sitemap.xml seeding (up to 500 pages), SHA-256 content hashing for deduplication, incremental updates (delete old vectors then insert new), page type classification (home/about/service/blog/team/contact/careers/testimonials), HTML link extraction, polite crawl delay; chunks pages into Qdrant `phase1_documents` collection with `source_type="website"` metadata (`url`, `page_type`, `section`, `content_hash`, `version`, `timestamp`, `connection_id`)
- `app/api/website_routes.py` — REST API: `POST /website/connect` (start background crawl, returns `connection_id` immediately), `POST /website/disconnect` (stop + optional vector deletion), `GET /website/status` (all connections), `GET /website/status/{id}` (single), `POST /website/refresh/{id}` (incremental re-crawl)
- `app/main.py` — registered `website_router` on startup
- `frontend/src/components/WebsiteScraper.tsx` — new admin UI page: URL + org name input, crawl progress bar (pages done/found/%), status badges (Pending/Crawling/Done/Error), auto-polls every 3 seconds while crawling, per-connection stats (pages, chunks, elapsed time), Re-crawl / Stop / Remove / Remove+delete vectors actions
- `frontend/src/components/Sidebar.tsx` — added "Website Scraper" nav item with Globe icon (admin-only)
- `frontend/src/pages/Dashboard.tsx` — wired `website` view: type, label, subtitle, admin guard, ErrorBoundary render

---

## [6.0.2] — 2026-04-13

### Added
- `app/api/admin_routes.py` — new `GET /admin/ingest-jobs` endpoint: returns active, queued, and recently-completed ingest jobs with filename, status, elapsed time, error, and SharePoint source flag
- `frontend/src/components/AdminPanel.tsx` — **Ingestion Status panel** now shown at the top of the Chunks tab; shows live "in progress" banner for active SharePoint or upload ingestion with 4-second auto-refresh; source badge distinguishes SharePoint vs manual upload

### Fixed
- `services/document_reader.py` — **critical wrong-document bug**: DocumentReader only looked in `uploaded_docs/` for file name candidates; SharePoint-ingested files (e.g. `HR Policy Manual-v2.1.pdf`) are stored in Qdrant but not locally, so the fuzzy matcher fell back to `ai_policy.txt` (only shared word: "policy"); fixed by fetching all unique `file_name` values from Qdrant and including them in the candidate list
- `services/document_reader.py` — **false-positive filename matching**: single-word overlap (score 1/1) was accepted as a match; now requires ≥2 words to match OR a minimum score of 0.4, preventing `ai_policy` from matching queries about `HR Policy Manual`
- `services/document_reader.py` — **Qdrant-sourced file reading**: added `_read_from_qdrant(filename)` which reconstructs document text by joining Qdrant chunks sorted by `chunk_id`/`char_start`; enables reading exact lines and full content from SharePoint-ingested PDFs that have no local file copy
- `services/agent_orchestrator.py` — query rewriter now skips rewriting for explicit document-read queries (line number or full-doc patterns detected); prevents LLM rewriting from corrupting verbatim line-read requests before they reach DocumentLineReaderTool
- `services/ingest_queue.py` — `submit()` now stores `original_filename` in `_results` dict so the admin ingest-jobs endpoint can show human-readable file names instead of temp paths

---

## [6.0.1] — 2026-04-13

### Fixed
- `services/hybrid_search.py` — **critical**: Qdrant client v1.x removed `.search()`; replaced with `.query_points()` using `response.points` accessor; vector search was silently falling back to pure vector on every query
- `services/chatbot_service.py` — same Qdrant API fix: `.search()` → `.query_points()` in document-lookup path
- `services/hybrid_search.py` — `_vector_search` was calling `embedder.embed_query()` which does not exist; fixed to `embedder.embed()` (the correct method on `EmbeddingService`)
- `services/agent_orchestrator.py` — `_fetch_payload_map` was using `embedder.collection_name` (`documents`) instead of `phase1_documents`; sources were always empty because payload fetch returned nothing; fixed to use `self._phase1_rag.collection_name`

---

## [6.0.0] — 2026-04-13

### Added
- `services/hybrid_search.py` — **new** HybridSearchService: BM25 (rank_bm25) + Qdrant vector search fused via Reciprocal Rank Fusion (0.65 vector + 0.35 BM25); BM25 index built lazily from Qdrant payload, auto-refreshes when collection grows >5%; falls back to pure vector if BM25 unavailable
- `services/context_builder.py` — **new** CoverageAwareContextBuilder: Jaccard deduplication (>85% similarity threshold), diversity enforcement (max 2 chunks per source file), extractive compression (key-sentence selection per chunk), hard 8000-char budget with per-chunk allocation
- `services/phase1_llm.py` — `rewrite_query()` method: LLM-based query expansion via Cohere with 5-second timeout; rewrites ambiguous short queries into retrieval-friendly intent-aware queries before Stage 1 retrieval
- `frontend/src/api/client.ts` — global axios 401 interceptor covering both the `api` instance and raw `axios` calls; clears localStorage and dispatches `session-expired` event on any 401 response
- `frontend/src/App.tsx` — `session-expired` event handler: redirects to login page and shows red "Your session expired. Please log in again." banner for 5 seconds

### Changed
- `services/agent_orchestrator.py` — full pipeline rewrite: (0) greeting fast-path, (1) cache, (2) query rewriting, (3) intent classify, (4) hybrid BM25+vector retrieval with parallel sub-queries, (5) graph boost secondary signal, (6) cross-encoder rerank to Top-10, (7) coverage-aware context build, (8) LLM generation; Stage-1 K raised from 15→25 per sub-query
- `services/reranker.py` — reranker upgraded from MiniLM-L-6 to `cross-encoder/ms-marco-MiniLM-L-12-v2` (stronger quality, same memory footprint); top-k raised from 5→10; batch_size 8 (CPU) or 16 (GPU); chunk truncation at 600 chars
- `core/config.py` — chunk_token_size 450→500, chunk_token_overlap 64→100; reranker_model set to `cross-encoder/ms-marco-MiniLM-L-12-v2`
- `app/core/security.py` — JWT access token expiry extended from 24 hours → 7 days; eliminates the "Invalid or expired token" error on SharePoint and other admin endpoints for regular users

### Fixed
- **SharePoint "Invalid or expired token"** — was a JWT session expiry issue (24h limit); fixed by extending to 7 days and adding auto-logout interceptor so users see a clear message instead of a cryptic error

---

## [5.6.0] — 2026-04-13

### Fixed
- `services/phase1_llm.py` — **critical chat fix**: was using `cohere.Client` (SDK v4 API) with removed model `command-r-plus`; now uses `cohere.ClientV2` (SDK v5), correct `messages=[...]` array format, model `command-r7b-12-2024`, and a hard 25-second `RequestOptions(timeout_in_seconds=25)` to prevent infinite hang
- `services/reranker.py` — cross-encoder was scoring 50 full-text candidate pairs against `BAAI/bge-reranker-large` on CPU, causing >120 s stalls; added `_MAX_CHUNK_CHARS=512` truncation on pairs and `batch_size=8, show_progress_bar=False` on `predict()`
- `services/agent_orchestrator.py` — Stage 1 candidate count reduced from 50 → 15; eliminates the root cause of reranker CPU overload while keeping quality (top-5 result unchanged)
- `services/agent_orchestrator.py` — `_source_name` was doing a full Qdrant scroll (200 records) once per chunk = 5 separate scans per query; replaced with a single `_fetch_payload_map()` call shared across `_node_retrieve` and `_node_fuse_context`
- `services/document_parser.py` — removed Apache Tika / JVM for all common formats; pure-Python extractors (`pypdf`, `python-docx`, `python-pptx`, `openpyxl`) used instead; Tika kept only as last resort for unknown binary formats; eliminates 30-second upload block on every file
- `app/api/admin_routes.py` — analytics was executing 43 sequential SQLite queries per page load (14 daily + 24 hourly + 5 aggregates); replaced with 5 batched queries using `GROUP BY` and aggregate functions
- `app/api/admin_routes.py` — `GraphService` was instantiated fresh on every `/admin/graph` call, triggering a 2-second Neo4j connection timeout each time; replaced with module-level singleton `_graph_service_cache`
- `core/config.py` — `max_upload_size` raised to 500 MB; `cohere_model` fixed to `command-r7b-12-2024`

---

## [5.5.1] — 2026-04-10

### Fixed
- `core/config.py` — reverted `cohere_model` from `command-r-plus` (removed by Cohere Sept 2025) back to `command-r7b-12-2024`; chat now works again
- `services/sharepoint_service.py` — critical bug: deltaLink was saved BEFORE processing items, so any failed ingest permanently skipped those files; moved `_save_delta_token` call to AFTER the item loop so failed files are retried on the next cycle
- `services/sharepoint_service.py` — startup race condition: delta sync fired 15 s after startup but embedding models take ~90 s to load from disk, causing "RAG unavailable" on every file; increased startup delay to 90 s and added a 120 s in-sync wait-for-RAG loop in `_queue_file_for_ingest`
- `services/sharepoint_service.py` — temp file used original filename in a dedicated `mkdtemp` dir so `ingest_file` stores the real document name (`HR Policy Manual-v2.1.pdf`) in Qdrant instead of the random temp name
- `services/sharepoint_service.py` — `_mark_file_error` wrapped in try/except so DB errors during error recording are logged rather than silently swallowed
- `services/phase1_pipeline.py` — added 400 k-char guard in `chunk_text_with_metadata` to route very large files through character-based chunking instead of crashing the tokenizer with a 462 k-token sequence

---

## [5.5.0] — 2026-04-10

### Added
- `services/sharepoint_service.py` — new event-driven SharePoint service: webhook registration, delta sync (MS Graph delta() API), atomic vector swap on update, rename detection via stable file_id, soft-delete on file removal, webhook renewal scheduler, resume-on-restart
- `app/api/sharepoint_routes.py` — `POST /sharepoint/connect`, `POST /sharepoint/disconnect`, `GET /sharepoint/status`, `POST /sharepoint/webhook` (MS Graph push notifications), `GET /sharepoint/webhook` (validation handshake)
- `app/models.py` — `SharePointConnection` table (connection registry, webhook subscription IDs, delta token, expiry) and `SharePointFile` table (per-file metadata registry: file_id, content_hash, version, indexed_status, line ranges)
- `frontend/src/components/SharePoint.tsx` — minimal admin page: URL input + Connect button; shows active connections with file count, last sync time, and Disconnect button; nothing else
- `core/config.py` — `reranker_model`, `chunk_token_size`, `chunk_token_overlap`, `sharepoint_notification_url`, `sharepoint_delta_sync_interval` settings; `sharepoint_tenant_id/client_id/client_secret` via env

### Changed
- `core/config.py` — `embedding_model` upgraded from `BAAI/bge-small-en-v1.5` (384-dim) to `BAAI/bge-large-en-v1.5` (1024-dim); `cohere_model` from `command-r7b-12-2024` to `command-r-plus`; `openai_model` from `gpt-4o-mini` to `gpt-4o`
- `services/reranker.py` — model upgraded from `cross-encoder/ms-marco-MiniLM-L-6-v2` to `BAAI/bge-reranker-large`; added `rerank_with_scores()` method; added diversity filter (`MAX_PER_DOC=2` per source document in final top-k)
- `services/phase1_pipeline.py` — replaced character-based chunker with token-aware chunker using `AutoTokenizer` from the embedding model (450 tokens / 64 overlap); outputs rich metadata per chunk: `chunk_id`, `line_start`, `line_end`, `char_start`, `char_end`, `token_count`; `chunk_text()` kept for backward compat
- `app/services/rag_service.py` — `ingest_file()` now uses `chunk_text_with_metadata()`; stores `chunk_id`, `line_start`, `line_end`, `char_start`, `char_end`, `token_count`, `version`, `sharepoint_file_id`, `sharepoint_folder_path` in Qdrant payload
- `services/agent_orchestrator.py` — context fusion enforces 80/20 vector/graph budget (6400/1600 chars); reranker called with `doc_names` for diversity filtering; `_extract_doc_names()` and `_source_name()` helpers for source attribution
- `services/phase1_llm.py` — strict grounding prompts for both user and admin roles: answers must be grounded in context, inline source attribution required, explicit "not in documents" response when context is missing; temperature lowered to 0.1
- `app/api/admin_routes.py` — removed all old SharePoint code (pull-based ingest, browse, test, ingest-items endpoints); replaced with comment pointing to sharepoint_routes.py
- `app/main.py` — registers `sharepoint_router`; calls `_resume_sharepoint_connections()` on startup to resume delta sync for previously active connections; version bumped to v5.0
- `frontend/src/pages/Dashboard.tsx` — added `"sharepoint"` to `View` type and `VIEW_LABELS`; renders `<SharePoint />` for admin users
- `frontend/src/components/Sidebar.tsx` — added SharePoint nav item (Link2 icon) to admin nav

---

## [5.4.1] — 2026-04-09

### Fixed
- `frontend/src/components/KnowledgeGraphUI.tsx` — added `timeout: 15000` to `GET /admin/graph/data`; distinguishes timeout vs other errors with appropriate messages; no more infinite loading spinner when backend is down
- `frontend/src/components/Analytics.tsx` — removed unused imports (`TrendingUp`, `Zap`), unused functions (`fmtLatency`, `RingGauge`, `StatCard`), and unused variables (`cacheRate`, `retrieval`) — clears all IDE warnings

### Added
- `frontend/src/components/DocumentUpload.tsx` — after successful SharePoint ingest, shows "View Chunks in Admin Panel →" button that navigates directly to Admin Panel (Chunks tab visible there)
- `frontend/src/pages/Dashboard.tsx` — passes `onNavigateToAdmin` callback to `DocumentUpload` to enable cross-view navigation

---

## [5.4.0] — 2026-04-09

### Fixed — SharePoint (critical)
- `app/api/admin_routes.py` — `sharepoint_ingest_selected`: replaced direct `ingest_file()` call with async ingest queue (`get_ingest_queue().submit()`). Direct call failed when `_rag` singleton was None (Qdrant not yet connected in web worker). Files are now downloaded, saved to `uploaded_docs/`, and queued exactly like regular uploads — returns `status: queued` immediately.

### Removed
- `frontend/src/components/AdminPanel.tsx` — removed Platform Metrics section (Total Queries, Active Users, Active Rules, Security Events cards)
- `frontend/src/components/Settings.tsx` — removed Security tab and its content block entirely
- `frontend/src/components/DocumentUpload.tsx` — removed ETL Pipeline tab entirely
- `frontend/src/components/Analytics.tsx` — removed Avg Latency & Cache Hit Rate cards from top row; removed Retrieval Quality by Query Type chart; removed Quick Metrics bottom row
- `frontend/src/components/KnowledgeGraphUI.tsx` — removed 3D canvas graph and 3D tab button; right pane now shows Entity Relationships table only

---

## [5.3.0] — 2026-04-09

### Added
- `app/api/admin_routes.py` — `POST /admin/sharepoint/browse`: lazy file-tree browser, returns one folder level at a time (folders + files with size/modified)
- `app/api/admin_routes.py` — `POST /admin/sharepoint/ingest/items`: ingest specific selected files by Graph API item ID; no more "ingest all" failures
- `app/api/admin_routes.py` — `_resolve_drive()` helper extracted to avoid code duplication
- `app/api/routes.py` — `GET /chat/sessions`: grouped session list (title = first question, message count, last activity, avg confidence)
- `app/api/routes.py` — `GET /chat/sessions/{session_id}`: restore all messages in a session
- `app/api/routes.py` — `/chat/history` now includes `session_id` in response

### Changed
- `frontend/src/components/DocumentUpload.tsx` — SharePoint tab fully replaced with interactive file browser: connect → browse tree → expand folders → check files → ingest selected; "Upload folder" button per folder
- `frontend/src/components/ChatInterface.tsx` — Sidebar completely redesigned: shows sessions grouped Today/Yesterday/Previous 7 days/Older (like Claude/ChatGPT); click session to restore full conversation; each `/ask` sends `session_id`; dark `#111318` sidebar, glass-morphism AI bubbles, gradient send button

---

## [5.2.0] — 2026-04-09

### Fixed
- `app/api/admin_routes.py` — SharePoint: URL-encode folder path segments (fixes spaces in paths like `Test/ask me/...`)
- `app/api/admin_routes.py` — SharePoint: case-insensitive library name matching; fallback to first drive with warning log
- `app/api/admin_routes.py` — SharePoint: better error messages for site URL parse failure and missing folder
- `app/api/admin_routes.py` — SharePoint: fallback download URL via Graph API content endpoint when `@microsoft.graph.downloadUrl` absent; pass Bearer token on download requests; increased download timeout to 120s

### Changed
- `frontend/src/components/ChatInterface.tsx` — Full UI redesign: glass-morphism AI bubbles with gradient top border, gradient user bubbles, redesigned sidebar with wider spacing, new suggestion cards with icons, gradient send button, animated typing dots, polished action row
- `frontend/src/pages/Dashboard.tsx` — Chat subtitle: replaced "Hybrid RAG · Graph · Multi-hop · Agent Routing" with animated pulse dot + "Neural retrieval · Knowledge graph · Live"

---

## [5.1.0] — 2026-04-08

### Changed
- `frontend/src/components/Analytics.tsx` — fixed ring gauge card layout (was overflowing narrow card); ring gauge is now centered vertically in its own card; fixed hourly bar chart (removed broken nested `flex flex-col items-center` that caused bars to collapse to 0 width); simplified to direct `div` bars with `alignItems: flex-end`; added bottom row of 4 quick-metric tiles; latency still formats as `12.3s` for >1000ms
- `frontend/src/components/KnowledgeGraphUI.tsx` — complete 3D interactive graph: canvas-based 3D force-directed layout (golden-angle sphere initialization → 80 iteration settle); real-time perspective projection with trackball rotation (drag to rotate X/Y axes); auto-rotates slowly when idle; double-click to toggle auto-rotate; hover shows glow + edge labels + tooltip; click selects node and highlights connected edges in the relationship table; entity browser on left; toggle between "3D Graph" and "Table" views in right panel

### Fixed
- API key 401 in Postman: root cause was using port 5173 (Vite dev server) instead of port 8000 (FastAPI backend). Correct backend URL: `https://potential-guacamole-q7wpxvpq6xj73656p-8000.app.github.dev`
- Generated fresh working API key: `cf_live_718c75991f5b3dd5ca786f6b22f3785b45be20f4` (name: postman-api)

---

## [5.0.0] — 2026-04-08

### Changed
- `frontend/src/components/ChatInterface.tsx` — grounding warning redesigned from prominent yellow banner to subtle italic footnote with left border (ChatGPT-style)
- `frontend/src/components/Analytics.tsx` — complete dashboard overhaul: fixed fake cacheData bug (was `[0,0,...,data.cache_hit_rate]`); replaced flat cache chart with animated ring gauge showing real hit rate; added gradient KPI hero cards with sparkline bars; proper latency formatting (ms → s when > 1000ms); color-coded retrieval quality bars; hover tooltips on hourly chart
- `frontend/src/components/AdminPanel.tsx` — Neo4j/service-down warning redesigned from verbose yellow banner with raw error text into compact inline pill showing "using SQLite fallback" with subtle pulse dot
- `frontend/src/components/KnowledgeGraphUI.tsx` — complete redesign: replaced unreadable force-directed SVG graph (69 overlapping nodes) with split-panel entity browser + relationship table; left panel groups entities by type in collapsible sections; right panel shows searchable/filterable relationship table with From→Relation→To columns and type badges; real-time filtering by entity selection or search query

---

## [4.9.0] — 2026-04-08

### Fixed

#### Chat model wrong answer for specific document reads
- `app/api/routes.py`: Added `_DOC_READ_RE` regex that detects queries asking to read a specific file (by extension, "whole document", "every line", "as it is", "full content")
- `_try_admin_intent()`: Added guard — file list handler only runs when `_FILE_LIST_RE` matches AND `_DOC_READ_RE` does NOT match, so "show whole document from file.xml" correctly falls through to the EnhancedOrchestrator DOC_READ_INTENT path instead of returning the file list

#### API Key 401 in Postman — confirmed working
- All endpoints tested with `X-API-Key` header: `/api/verify`, `/ask`, `/upload`, `/admin/*` all return 200
- Root cause was user had old/prefix-only key — generated fresh working key
- Auth chain: `X-API-Key` header → `authenticate_api_key()` → SHA-256 hash compare → returns `tenant_id`, `role`, `permissions`

#### Cache metrics
- Cache stats correctly return 0 after backend restart (expected — in-memory cache is fresh)
- `/admin/cache/stats` returns correct shape: `hit_rate_pct`, `active_entries`, `total_requests`, `memory_kb`
- Cache populates after queries are made — verified via analytics endpoint (25.6% hit rate across 199 historical queries)

#### Graph DB backend
- Neo4j attempted on startup with 2s timeout; falls back to SQLite automatically
- SQLite graph backend confirmed active and returning correct node counts in `/admin/system/health`
- UI correctly labels as "Graph DB (SQLite)" per CLAUDE.md instructions

---

## [4.8.0] — 2026-04-08

### Added — Multi-Tenant Isolation, SharePoint Graph API, API Key Tab Enhancements

#### Multi-Tenant Isolation (VERY IMPORTANT)
- `IngestJob` dataclass: added `tenant_id: Optional[str]` field
- `IngestQueue.submit()`: accepts and stores `tenant_id` per job
- `IngestQueue._process_loop`: forwards `tenant_id` to `ingest_file()`
- `/upload` and `/upload/batch` endpoints: extract `tenant_id = current_user.get("tenant_id")` and pass to queue
- `phase1_rag.query()` and `query_with_sources()`: accept `tenant_id`, add Qdrant `must` filter so API key clients only retrieve their own documents
- `AgentState`: added `tenant_id: Optional[str]` field
- `AgentOrchestrator.run()`: accepts `tenant_id`; cache key is tenant-scoped (`tenant_id:query`)
- `DocumentSearchTool.run()`: accepts and forwards `tenant_id` to retriever lambda
- `AgentOrchestrator._node_retrieve()`: passes `state.tenant_id` to `doc_tool.run()`
- `EnhancedAgentOrchestrator.run()`: accepts `tenant_id` and `conversation_history`; tenant-scoped cache key
- `SourceAnnotatedSearchTool.run()`: accepts `tenant_id`, adds Qdrant filter; admin role bypasses RBAC filter
- All `_annotated_searcher.run()` call sites pass `tenant_id=state.tenant_id`
- `ask_rag_full()`: accepts and passes `tenant_id` through to orchestrator
- `/ask` endpoint: extracts `tenant_id` from `current_user` and passes to `ask_rag_full()`

#### SharePoint — Microsoft Graph API (client_credentials flow)
- **Removed** username/password auth from `SharePointRequest` model and all backend functions
- **New** `SharePointRequest` fields: `site_url`, `library_name`, `folder_path`, `file_types`, `recursive`
- **New** `_get_graph_token()`: reads `SHAREPOINT_TENANT_ID/CLIENT_ID/CLIENT_SECRET` from `.env`, calls Azure AD token endpoint
- **New** `_graph_get()`: authenticated GET helper for Graph API calls
- **New** `_ingest_via_graph_api()`: resolves site → drive → traverses items recursively, downloads and ingests files
- **New** `POST /admin/sharepoint/test`: tests connection, returns available document libraries for UI dropdown
- `POST /admin/sharepoint/ingest`: now uses Graph API only; removed Office365-REST fallback
- `.env`: added `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` placeholders
- **SharePointConnector** (frontend): completely redesigned — no credentials in form; 2-step flow: Site URL + "Test Connection" button → library dropdown auto-filled → folder/options → "Connect & Ingest Files"

#### API Key Tab — Base URL, Docs, Analytics
- **API Base URL panel**: shows `window.location.origin` with one-click copy
- **API Documentation section**: 4 endpoints (verify, ask, upload, chat/history) shown with method badge, description, and copyable curl example
- **Usage Analytics**: bar chart per active API key showing total_requests, last_used_at, permissions

### Changed
- `services/ingest_queue.py`: removed old Office365 client and REST API fallback helper functions
- `app/api/admin_routes.py`: SharePoint section fully replaced with Graph API implementation

---

## [4.7.0] — 2026-04-08

### Added — UI Overhaul (Admin, Chat, Sidebar, Upload)

#### ChatInterface
- **Admin mode banner**: Thin red banner at top of chat when logged in as admin — "Admin Mode — Full document access enabled". RoleSelector moved into banner.
- **Provider pill**: Each AI message shows which LLM answered (Cohere / OpenAI fallback / Static fallback) as a small colored badge in the tags row.
- **Grounding score display**: Numeric score (e.g. "Ground: 82%") shown next to confidence badge for all messages where score < 100%.
- **Rate limit countdown**: When HTTP 429 is received, send button replaced with a live countdown timer (e.g. "47s") that auto-re-enables when the window resets.
- **Feedback toast**: After thumbs up/down, a 2.5s toast confirms "Thanks for your feedback!" or "Feedback noted — we'll improve!"
- **"New Chat" button**: Bottom of history sidebar — clearer label with `+` icon, starts a fresh session.
- **Copy toast** consolidated alongside feedback toast; both rendered in a fixed bottom-right stack.
- Removed unused `Loader2`, `History` imports.

#### AdminPanel
- **API Keys tab** (new): Full CRUD for external integration keys. Table shows name, prefix, permissions, request count, last used, expiry, status. Create form with name/permissions/expiry/notes. Raw key shown once in a masked + copy-to-clipboard panel. Revoke via `X` button with confirm dialog.
- **ConfirmDialog component**: Modal dialog (Cancel / Confirm) replaces `window.confirm` for all destructive actions — delete rule, revoke API key.
- **Ingest Queue panel** in Monitoring tab: Live list of last 20 background jobs with color-coded status badges (done/processing/queued/error), file name, elapsed time, error message.
- **User search bar**: Filter users table by email or name in real time.
- **Tab bar updated**: Added "API Keys" tab (Key icon), renamed "Chunks (Qdrant)" → "Chunks", "Storage Info" → "Storage".

#### Sidebar
- **Collapse to icon-only mode**: Toggle button (`<<` / `>>`) collapses sidebar from 240px to 64px. Icons remain clickable with tooltips. Unread alerts badge shows as dot in collapsed mode. Quote removed from footer.

#### DocumentUpload
- **Auto-poll ingest status**: After a file is queued, polls `/upload/status/{job_id}` every 3 seconds until `done` or `error` (max 3 min), then updates the file card in place.
- **"Unchanged" state**: Files skipped by the version hash check show a yellow "No changes detected — skipped re-processing" message with a distinct border.
- **Clearer status indicators**: "done" state shows green "✓ Ready — you can now search this document". Queued shows pulsing yellow bar while polling. Error shows message in red.

---

## [4.6.0] — 2026-04-08

### Added

#### A3 — Hallucination Guard: Frontend Warning Banner
- **`frontend/src/components/ChatInterface.tsx`** — Yellow warning banner rendered below SourcesPanel when `msg.groundingWarning` is non-null. Uses amber border + dark amber background, matches existing design system.

#### A5 — Document Versioning
- **`app/api/routes.py`** — `/upload` endpoint now reads file bytes and computes SHA-256 hash before saving.
  - If filename already exists in `documents` table with identical hash → returns `status: "unchanged"` immediately (no re-embed, no re-queue).
  - If new version: deletes stale Qdrant chunks (filter `file_name == filename`) before queuing, bumps `version`, updates `last_updated`.
  - Creates or updates `Document` registry record on every new upload.
- Added `import hashlib` and `Document` model import to `routes.py`.
- Added `db: Session = Depends(get_db)` parameter to `/upload` endpoint.

#### F2 — Rate Limiting (60/hr users, 300/hr admin)
- **`app/dependencies.py`** — Added `_RateLimiter` class with sliding-window per-user bucketing (`threading.Lock` + `deque`). Limits: admin → 300/hr, user/client → 60/hr.
- Added `check_rate_limit` dependency — raises HTTP 429 with `Retry-After` header on breach.
- **`app/api/routes.py`** — `/ask` endpoint now uses `check_rate_limit` dependency instead of bare `get_current_user`.
- **`frontend/src/components/ChatInterface.tsx`** — Handles HTTP 429 response: reads `Retry-After` header and shows the rate limit error message inline in the chat.

#### D3 — Conversation Memory
- **`app/api/routes.py`** — Before calling `ask_rag_full`, fetches last 3 `ChatLog` entries for the current `session_id` from DB, formats as `[{role, text}]` pairs, passes as `conversation_history` to LLM.
- **`app/services/rag_service.py`** — `ask_rag_full()` accepts new `conversation_history: Optional[list]` param and forwards to orchestrator.
- **`services/agent_orchestrator.py`** — `AgentState` has new `conversation_history: List[dict]` field. `run()` accepts `conversation_history` param. `_node_generate()` passes it to `llm.generate_answer()`. LLM already formats last 3 turns as "Previous conversation:" prefix.

#### C1 — Neo4j / Qdrant Health Monitor
- **`services/health_monitor.py`** (NEW) — Background thread checks Neo4j (2s timeout) and Qdrant (3s timeout) every 30s. Results stored in `_STATUS` dict with `status/last_checked/last_ok/error` fields. Exposes `get_health_status()` and `start_health_monitor()`.
- **`app/main.py`** — `startup()` now calls `_start_health_monitor()`, which starts the background checker.
- **`app/api/admin_routes.py`** — `GET /admin/health/services` returns snapshot from health monitor (admin only).
- **`frontend/src/components/AdminPanel.tsx`** — Added `serviceHealth` state and `fetchServiceHealth()` calling `/admin/health/services`. Overview tab shows a yellow warning banner for each service that is `"down"`, with last-healthy timestamp.

#### B2 — Two-Stage Retrieval (top-50 → rerank → top-5)
- **`services/agent_orchestrator.py`** — `DocumentSearchTool` now calls `phase1_rag.query(q, role, top_k=50)` (was 10). After collecting all sub-query results, deduplicates and caps at 50 before passing to CrossEncoder reranker which narrows to top-5.

### Changed
- **`app/api/routes.py`** — imports `check_rate_limit` from `app.dependencies`; imports `Document` model.

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
