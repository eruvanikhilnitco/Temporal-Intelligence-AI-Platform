# CortexFlow AI — Enterprise Knowledge Intelligence Platform

> Production-grade AI platform combining Hybrid RAG, Knowledge Graphs, Role-Based Access Control, Multi-Document Cross-Retrieval, and a full Admin Dashboard — built by Team Nitco Inc.

[![Version](https://img.shields.io/badge/version-4.4.0-blue)](.) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](.) [![React](https://img.shields.io/badge/React-18-blue)](.) [![Neo4j](https://img.shields.io/badge/Neo4j-5.18-brightgreen)](.) [![License](https://img.shields.io/badge/license-MIT-gray)](.)

---

## Architecture

```
Browser (React 18 + Vite + TypeScript)
    │
    ▼
FastAPI Backend (Python 3.12)
    ├── Phase 1 · RAG           — Qdrant vector search + BAAI/bge-small-en-v1.5 (384-dim)
    ├── Phase 2 · Intelligence  — Enhanced Orchestrator, query classifier, reranker, TTL cache
    └── Phase 3 · Graph RAG     — Neo4j knowledge graph (SQLite fallback) + multi-hop retrieval
         │
         ├── Neo4j   (bolt://localhost:7687)  — entity graph, cross-document links (primary)
         ├── SQLite  (cortexflow.db)          — users, chat logs, rules, security events
         └── Qdrant  (port 6333)              — 384-dim vector embeddings for document chunks
```

**LLM:** Cohere `command-r7b-12-2024` via `COHERE_API_KEY`
**Embedding:** `BAAI/bge-small-en-v1.5` — 33M params, 384-dim, ~1.2s/query on CPU (6× faster than bge-large)
**Graph DB:** Neo4j primary, SQLite automatic fallback (2s connection timeout)

---

## Quick Start

### Step 1 — Start Infrastructure

```bash
# Start Neo4j (knowledge graph)
docker compose up -d neo4j

# Start Qdrant (vector store) — restart existing container
docker start qdrant_cf

# If no qdrant_cf container exists yet:
# docker run -d -p 6333:6333 -p 6334:6334 --name qdrant_cf qdrant/qdrant
```

### Step 2 — Start Backend

```bash
cd /workspaces/Temporal-Intelligence-AI-Platform

# Install dependencies (first time only)
pip install -r requirements.txt

# Add your API key to .env
echo "COHERE_API_KEY=your-key-here" >> .env

# Start server (auto-reload on file changes)
python run.py
```

- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

> On first startup, the embedding model (~130 MB) is pre-warmed in a background thread. First query may be slightly slower while the model loads.

### Step 3 — Start Frontend

```bash
cd /workspaces/Temporal-Intelligence-AI-Platform/frontend

npm install       # first time only
npm run dev       # development server → http://localhost:5173
npm run build     # production build
```

### Step 4 — Neo4j Browser (optional)

- URL: http://localhost:7474
- Login: `neo4j` / `password123`
- Query: `MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50`

---

## Default Credentials

| Email | Password | Role |
|-------|----------|------|
| `admin@test.com` | `admin123` | admin |
| `user@test.com` | `user123` | user |

**Register new accounts:**
- Admin: `/signup/admin`
- User: `/signup/user`

---

## Features

### Chat (All Users)
- Hybrid RAG: vector + knowledge graph retrieval fused into a single context
- Role-aware answers: **Admin** gets technical precision; **User** gets warm, conversational summaries
- **Stop button** — cancel any in-flight query instantly (browser AbortController)
- Graph / Cache / Confidence badges on every response
- ChatGPT-style history sidebar — conversations persist across sessions
- Cached queries return in <100ms (TTL-based in-memory cache, 600s default)
- Cross-document queries: compare information spanning multiple uploaded files

### Document Upload
- Drag-and-drop or browse: PDF, DOCX, TXT, JSON, CSV, HTML, PPTX, XML, MD
- **Non-blocking ingestion** — upload returns "queued" status immediately; background worker handles parsing, chunking, embedding, and graph extraction
- Folder upload: recursive multi-file ingestion via `webkitdirectory` API
- SharePoint Online: connect with username/password, recursive library traversal
- ETL pipeline view: live status of background ingest jobs
- Auto metadata extraction: domain, doc_type, sensitivity — keyword/entity-driven, no hardcoding

### Document Security
- All newly ingested documents are `admin`-only by default
- Non-admin users are blocked from requesting raw documents, file names, or system internals
- Exfiltration attempts (20+ regex patterns) are logged as `high`-severity SecurityEvents
- Admin is alerted in the Security tab when a user attempts data extraction

### Knowledge Graph (Admin)
- Neo4j primary backend; falls back to SQLite if Neo4j is unreachable (2-second timeout)
- Entity types: Contracts, Dates, Amounts, Organizations
- Cross-document links (`SHARES_ENTITY_WITH`) created automatically at ingest
- Force-directed visualization with zoom, search, type filters

### Admin Panel

| Tab | Description |
|-----|-------------|
| Overview | Live system health: Qdrant, Graph DB, LLM, Auth status |
| Users | List, block/unblock, role management |
| Security | Event log (high/medium/low), severity filters, resolve events |
| Rule Engine | Create/toggle/delete RBAC content guardrail rules |
| Monitoring | Cache hit rate, memory usage, query latency, hourly chart |
| Chunks (Qdrant) | Browse chunks grouped by document in collapsible folders; delete files |
| Storage Info | SQLite/Neo4j stats + Qdrant collection status |
| Error Log | View, filter, and clear structured error log |

### Single-Line / Full Document Retrieval
- "Retrieve line 40 from [document]" → returns exact verbatim line
- "Show me the full contents of [document]" → returns entire document
- Supports: retrieve, get, fetch, show, display, read, extract, give, open, view, look at
- Ordinal patterns: "line 40", "40th line", "line:40", "fortieth line"

---

## API Reference

### Core Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check |
| POST | `/ask` | JWT | Ask a question (full RAG pipeline) |
| GET | `/ask/stream` | JWT | SSE streaming response |
| POST | `/upload` | JWT | Upload and queue a single file |
| GET | `/upload/status/all` | JWT | List all background ingest jobs |
| GET | `/upload/status/{job_id}` | JWT | Status of a specific ingest job |
| POST | `/feedback` | JWT | Submit thumbs up/down on a response |
| GET | `/chat/history` | JWT | User's chat history |

### Admin Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/errors` | Recent structured error log entries |
| GET | `/admin/errors/stats` | Error counts by level / source |
| DELETE | `/admin/errors` | Clear error log |
| GET | `/admin/cache/stats` | Cache hit rate, memory usage, active entries |
| DELETE | `/admin/cache` | Clear the query cache |
| GET | `/admin/document/list` | All uploaded documents |
| GET | `/admin/document/read` | Read a document by line or full content |
| PUT | `/admin/document/access` | Set access roles for a document |
| GET | `/admin/document/access` | Get access roles for a document |
| DELETE | `/admin/document/{filename}` | Remove file from Qdrant + disk |
| POST | `/admin/sharepoint/ingest` | Ingest from SharePoint Online |
| GET | `/admin/system/health` | Detailed system component status |
| GET | `/admin/storage/info` | Storage stats (SQLite + Qdrant) |
| GET | `/admin/security/stats` | Security event counts + recent events |

---

## Data Storage

| Data | Location |
|------|----------|
| Users, chat logs, security events, rules | `cortexflow.db` — SQLite (project root) |
| Knowledge graph (nodes + edges) | Neo4j `bolt://localhost:7687`; fallback: `cortexflow.db` |
| Document vector embeddings (384-dim) | Qdrant — collections `documents`, `phase1_documents` |
| Uploaded files | `uploaded_docs/` directory |
| Error log | `logs/error_log.jsonl` + `logs/error_log.txt` |

**View SQLite data:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('cortexflow.db')
print('Users:'); [print(' ', r) for r in conn.execute('SELECT email, role FROM users')]
print('Graph nodes:', conn.execute('SELECT COUNT(*) FROM graph_nodes').fetchone()[0])
conn.close()
"
```

---

## Environment Variables

```env
# Required
SECRET_KEY=your-secret-key-min-32-chars
COHERE_API_KEY=your-cohere-api-key

# Qdrant (defaults work if using docker start qdrant_cf)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Neo4j (started via docker compose up -d neo4j)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# Optional fallbacks
OPENAI_API_KEY=your-openai-key
```

> `.env` is in `.gitignore` — never commit it.

---

## Project Structure

```
├── app/
│   ├── api/
│   │   ├── routes.py           Chat, upload, health, streaming endpoints
│   │   ├── admin_routes.py     Admin CRUD, cache, document delete, error log
│   │   └── auth_routes.py      JWT login, signup, token refresh
│   ├── services/
│   │   └── rag_service.py      Orchestrator + ingest pipeline wiring
│   ├── error_logger.py         Structured JSON Lines error logging
│   ├── models.py               SQLAlchemy ORM models
│   ├── db.py                   DB engine (PostgreSQL → SQLite fallback)
│   └── main.py                 App entry point, middleware, startup hooks
├── services/
│   ├── phase1_rag.py           Vector retrieval (Qdrant, 384-dim)
│   ├── phase1_pipeline.py      Document parse → chunk → embed pipeline
│   ├── embedding_service.py    BAAI/bge-small-en-v1.5 with process-level embed cache
│   ├── ingest_queue.py         Background FIFO ingest queue (non-blocking uploads)
│   ├── graph_service.py        Neo4j graph (2s timeout, SQLite fallback)
│   ├── graph_rag.py            Hybrid vector + graph context fusion
│   ├── agent_orchestrator.py   LangGraph-style pipeline: classify → retrieve → fuse → generate
│   ├── enhanced_orchestrator.py  DocRead, CrossDoc, metadata-aware routing
│   ├── cache_service.py        TTL-aware in-memory cache (600s default, thread-safe)
│   ├── phase1_llm.py           Cohere LLM wrapper with role-aware prompts
│   ├── self_learning.py        Session memory, feedback loop, query enrichment
│   └── security_service.py     Threat detection, PII masking, attack scoring
├── core/
│   ├── config.py               Settings (embedding model, DB URLs, API keys)
│   └── database.py             DB connectors + get_neo4j_driver(timeout=2.0)
├── frontend/
│   └── src/
│       ├── pages/              Landing, Dashboard, Login, SignUp
│       └── components/         ChatInterface, AdminPanel, DocumentUpload, Analytics
├── logs/                       Auto-created error logs
├── docker-compose.yml          Neo4j service
├── cortexflow.db               SQLite database (auto-created)
├── uploaded_docs/              Uploaded document storage
├── CLAUDE.md                   AI assistant instructions for this codebase
├── GUARDRAILS.md               Content safety and access control policy
├── CHANGELOG.md                Full version history
└── requirements.txt            Python dependencies
```

---

## Performance

| Metric | Value |
|--------|-------|
| Query embedding (bge-small, CPU) | ~1.2s per call |
| Qdrant vector search | ~50ms |
| Cohere LLM API | ~1–3s |
| **Typical end-to-end latency** | **3–6s** |
| Cached query (same question again) | **<100ms** |
| Upload response time | **Instant** (async queue) |
| Neo4j fallback to SQLite | ≤2s timeout |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Neo4j not connecting | `docker compose up -d neo4j` then wait 30s |
| Qdrant offline | `docker start qdrant_cf` |
| "No results" after upload | Wait for ingest job to complete — check `/upload/status/all` |
| Dimension mismatch error | Restart backend — it auto-detects and recreates the Qdrant collection |
| SharePoint 0 files | Check credentials; library path must be relative (e.g. `Shared Documents`) |
| Line retrieval "not found" | Verify exact document name matches what was uploaded |
| Slow first query | Embedding model warms up in background — takes ~10s after first start |

**Tail the error log:**
```bash
tail -f logs/error_log.txt
```

**Check API errors (admin token required):**
```bash
curl -H "Authorization: Bearer <admin_token>" http://localhost:8000/admin/errors?limit=20
```

**Check ingest queue:**
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/upload/status/all
```
