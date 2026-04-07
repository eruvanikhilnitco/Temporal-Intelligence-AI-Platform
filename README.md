# CortexFlow AI — Enterprise Knowledge Intelligence Platform

> Production-grade AI platform combining Hybrid RAG, Neo4j Knowledge Graphs, Role-Based Access Control, Multi-Document Cross-Retrieval, and a full Admin Dashboard.

[![Version](https://img.shields.io/badge/version-4.1.0-blue)](.) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](.) [![React](https://img.shields.io/badge/React-18-blue)](.) [![Neo4j](https://img.shields.io/badge/Neo4j-5.18-brightgreen)](.) [![License](https://img.shields.io/badge/license-MIT-gray)](.)

---

## Architecture

```
Browser (React 18 + Vite + TypeScript)
    │
    ▼
FastAPI Backend (Python 3.12)
    ├── Phase 1 · RAG           — Qdrant vector search + BAAI/bge-large-en-v1.5
    ├── Phase 2 · Intelligence  — Enhanced Orchestrator, query classifier, reranker, cache
    └── Phase 3 · Graph RAG     — Neo4j knowledge graph (SQLite fallback) + multi-hop retrieval
         │
         ├── Neo4j   (bolt://localhost:7687)  — entity graph, cross-document links
         ├── SQLite  (cortexflow.db)          — users, chat logs, rules, events
         └── Qdrant  (port 6333)              — vector embeddings for document chunks
```

---

## Quick Start

### Step 1 — Start Infrastructure

```bash
# Start Neo4j (knowledge graph) — only needed once per machine restart
docker compose up -d neo4j

# Qdrant should already be running; if not:
docker run -d -p 6333:6333 -p 6334:6334 --name qdrant_cf qdrant/qdrant
# or restart existing: docker start qdrant_cf
```

### Step 2 — Start Backend

```bash
cd /workspaces/Temporal-Intelligence-AI-Platform

# Install dependencies (first time only)
pip install -r requirements.txt

# Start server (with auto-reload)
python run.py
# or: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Step 3 — Start Frontend

```bash
cd /workspaces/Temporal-Intelligence-AI-Platform/frontend

# Install dependencies (first time only)
npm install

# Start dev server
npm run dev

# Production build
npm run build && npm run preview
```

- App: http://localhost:5173

### Step 4 — Neo4j Browser (optional)

- URL: http://localhost:7474
- Login: `neo4j` / `password123`

> PostgreSQL is **optional** — backend auto-falls back to SQLite.
> The BAAI embedding model (~500 MB) is pre-warmed in a background thread at startup.

---

## Default Credentials

| Email | Password | Role |
|-------|----------|------|
| `admin@test.com` | `admin123` | admin |
| `eruvabalu28@gmail.com` | `admin123` | admin |
| `user@test.com` | `user123` | user |

**Register new accounts:**
- Admin signup: `/signup/admin`
- User signup: `/signup/user`

---

## Features

### Chat (All users)
- Hybrid RAG: vector + knowledge graph retrieval
- **Admin**: full sources, citations, confidence scores, role selector
- **User**: clean summarized answers (150-word limit)
- ChatGPT-style history sidebar — conversations persist across page navigation
- Graph / Cache / Confidence badges on each response
- Cross-document queries: ask questions spanning multiple documents simultaneously

### Document Upload (Admin only)
- **Local files**: drag-and-drop PDF, XML, DOCX, TXT, JSON, CSV, HTML, PPTX, MD
- **Folder upload**: recursive folder ingestion via browser `webkitdirectory` API (nested subfolders supported)
- **SharePoint**: connect with username/password via Office365-REST-Python-Client; recursive library traversal
- Pipeline: Parse → Chunk → Embed (BAAI/bge-large-en-v1.5) → Store (Qdrant) → NER → Build Neo4j Graph
- Auto metadata extraction: domain, doc_type, sensitivity — no hardcoding, driven by keyword/entity scoring
- Access control: documents default to `admin`-only; promote via Admin Panel

### Single-Line / Full Document Retrieval
- "Retrieve 40th line from [document]" → returns exact verbatim line
- "Show me the full contents of [document]" → returns entire document
- Supports: retrieve, get, fetch, show, display, read, extract, give, open, view, look at
- 6 ordinal patterns: "line 40", "40th line", "line:40", "on line 40", "fortieth line"

### Multi-Document Cross-Retrieval
- Detects compare/contrast queries mentioning multiple documents
- Queries each document independently with source labeling
- Returns per-source attributed context to LLM for accurate comparison

### Knowledge Graph (Admin only)
- Neo4j backend with automatic SQLite fallback if Neo4j is unreachable
- Entity types: Contracts, Dates, Amounts, Organizations
- Cross-document links: SHARES_ENTITY_WITH edges created automatically at ingest
- Force-directed visualization with zoom, search, and type filters

### Admin Panel

| Tab | Description |
|-----|-------------|
| Overview | Live system health: Qdrant, Neo4j, LLM, Auth |
| Users | List, block/unblock, role management |
| Security | Event log, severity filters, resolve events |
| Rule Engine | Create/toggle/delete RBAC content guardrail rules |
| Monitoring | Latency, cache hit rate, hourly query chart |
| Chunks (Qdrant) | Browse chunks grouped by document in collapsible folders |
| Storage Info | SQLite/Neo4j stats + Qdrant collection status |
| Error Log | View, filter, and clear structured error log (`GET /admin/errors`) |

### Document Access Control (Admin only)
- `PUT /admin/document/access` — set access roles for a document (`["admin"]`, `["user","admin"]`, etc.)
- `GET /admin/document/access` — query current roles for a document
- Secure by default: all newly ingested documents are `admin`-only unless they contain public release signals

### Analytics (Admin only)
- Total queries, avg latency, cache hit rate, confidence scores
- Daily query trend (14 days) + hourly distribution chart

### Error Logging (Automatic)
- Structured JSON Lines log: `logs/error_log.jsonl`
- Plain text mirror: `logs/error_log.txt`
- Every HTTP 5xx, unhandled exception, RAG failure, and ingest error is captured automatically
- Admin endpoints: `GET /admin/errors`, `GET /admin/errors/stats`, `DELETE /admin/errors`
- Each entry: timestamp, level, source, message, exception type, full traceback, request_id, path, user

---

## API Reference

### Core

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check |
| POST | `/ask` | JWT | Ask a question (RAG) |
| POST | `/upload` | Admin JWT | Upload a single file |
| POST | `/upload/batch` | Admin JWT | Upload a folder (multiple files) |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/errors` | Recent error log entries |
| GET | `/admin/errors/stats` | Error counts by level/source |
| DELETE | `/admin/errors` | Clear error log |
| GET | `/admin/document/list` | All uploaded documents |
| GET | `/admin/document/read` | Read a document line or full content |
| PUT | `/admin/document/access` | Set access roles for a document |
| GET | `/admin/document/access` | Get access roles for a document |
| POST | `/admin/sharepoint/ingest` | Ingest from SharePoint Online |
| GET | `/admin/system/health` | Detailed system component status |
| GET | `/admin/storage/info` | Storage stats (DB + Qdrant) |

---

## Data Storage

| Data | Location |
|------|----------|
| Users, chat logs, security events, rules | `cortexflow.db` — SQLite (project root) |
| Knowledge graph (nodes + edges) | Neo4j `bolt://localhost:7687` (SQLite fallback: `cortexflow.db`) |
| Document vector embeddings | Qdrant — collection `phase1_documents` |
| Uploaded files | `uploaded_docs/` directory |
| Error log | `logs/error_log.jsonl` + `logs/error_log.txt` |

**View SQLite data:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('cortexflow.db')
print('Users:'); [print(' ', r) for r in conn.execute('SELECT email, role FROM users')]
print('Graph nodes:', conn.execute('SELECT COUNT(*) FROM graph_nodes').fetchone()[0])
print('Chunks: see http://localhost:6333/dashboard')
conn.close()
"
```

**View Neo4j data (when running):**
- Browser: http://localhost:7474
- Cypher: `MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50`

---

## Environment Variables

Copy `.env.example` → `.env` and fill in your values:

```env
SECRET_KEY=your-secret-key-min-32-chars
COHERE_API_KEY=your-cohere-api-key

# Qdrant (default: localhost)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Neo4j — started via docker-compose up -d neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# OpenAI fallback (optional)
OPENAI_API_KEY=your-openai-key
```

> `.env` is in `.gitignore` — **never commit it**.

---

## Project Structure

```
├── app/                        FastAPI application
│   ├── api/
│   │   ├── routes.py           Chat, upload, health endpoints
│   │   ├── admin_routes.py     Admin CRUD, SharePoint, error log, document access
│   │   └── auth_routes.py      JWT login, signup, token refresh
│   ├── services/
│   │   └── rag_service.py      Orchestrator + ingest pipeline wiring
│   ├── error_logger.py         Structured error logging (JSON Lines)
│   ├── models.py               SQLAlchemy ORM models
│   ├── db.py                   DB engine (PostgreSQL → SQLite fallback)
│   └── main.py                 App entry point + middleware + startup
├── services/                   AI service layer
│   ├── phase1_rag.py           Vector retrieval (Qdrant)
│   ├── phase1_pipeline.py      Document parse → chunk → embed pipeline
│   ├── graph_service.py        Neo4j graph (SQLite fallback)
│   ├── graph_rag.py            Hybrid RAG orchestration
│   ├── enhanced_orchestrator.py  Decision engine: RAG / Graph / Hybrid / DocRead / CrossDoc
│   ├── document_reader.py      Verbatim line/document reader
│   ├── metadata_extractor.py   Auto domain/doc_type/sensitivity extraction
│   └── phase1_llm.py           LLM integration (Cohere → OpenAI fallback)
├── core/                       Config + database connectors
├── frontend/                   React 18 + TypeScript + Vite
│   └── src/
│       ├── pages/              Landing, Dashboard, Login, SignUp
│       └── components/         ChatInterface, AdminPanel, DocumentUpload, Analytics ...
├── logs/                       Error logs (auto-created)
│   ├── error_log.jsonl         Structured JSON Lines error log
│   └── error_log.txt           Plain text mirror
├── docker-compose.yml          Neo4j service definition
├── cortexflow.db               SQLite database (auto-created)
├── uploaded_docs/              Uploaded document storage
├── GUARDRAILS.md               Content safety and access control rules
├── CHANGELOG.md                Version history
└── requirements.txt            Python dependencies
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Neo4j not connecting | `docker compose up -d neo4j` then wait 30s |
| Qdrant offline | `docker start qdrant_cf` |
| BAAI model slow first load | Wait ~30-60s — it pre-warms in background |
| SharePoint 0 files | Check credentials; library path must be relative (e.g. `Shared Documents`) |
| Line retrieval "not found" | Verify exact document name matches what was uploaded |
| Error log is empty | Trigger a query — errors only appear when something goes wrong |

**Tail the error log:**
```bash
tail -f logs/error_log.txt
```

**Check API errors via admin:**
```bash
curl -H "Authorization: Bearer <admin_token>" http://localhost:8000/admin/errors?limit=20
```
