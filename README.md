# CortexFlow AI — Enterprise Knowledge Intelligence Platform

> Production-grade AI platform combining Hybrid RAG, Knowledge Graphs, Role-Based Access Control, and a full admin dashboard.

[![Version](https://img.shields.io/badge/version-4.0.0-blue)](.) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](.) [![React](https://img.shields.io/badge/React-18-blue)](.) [![License](https://img.shields.io/badge/license-MIT-gray)](.)

---

## Architecture

```
Browser (React 18 + Vite + TypeScript)
    │
    ▼
FastAPI Backend (Python 3.12)
    ├── Phase 1 · RAG           — Qdrant vector search + BAAI/bge-large-en-v1.5 embeddings
    ├── Phase 2 · Intelligence  — Query classifier, cross-encoder reranker, semantic cache
    └── Phase 3 · Graph RAG     — SQLite knowledge graph + multi-hop retrieval
         │
         ├── SQLite  (cortexflow.db)  — users, chat logs, rules, graph nodes/edges
         └── Qdrant  (port 6333)      — vector embeddings for document chunks
```

---

## Run Commands

Open **three terminals** and run one command in each:

### Terminal 1 — Qdrant (Vector Database)
```bash
# First time setup
docker run -d -p 6333:6333 -p 6334:6334 --name qdrant_cf qdrant/qdrant

# Subsequent starts (container already created)
docker start qdrant_cf
```
- Dashboard: http://localhost:6333/dashboard
- Collections API: http://localhost:6333/collections

---

### Terminal 2 — Backend (FastAPI)
```bash
cd /workspaces/Temporal-Intelligence-AI-Platform

# Install dependencies (first time only)
pip install -r requirements.txt

# Start server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

> PostgreSQL is **optional** — backend auto-falls back to SQLite.  
> The BAAI embedding model (~500 MB) is pre-warmed in a background thread at startup.

---

### Terminal 3 — Frontend (React + Vite)
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
- ChatGPT-style history sidebar — conversations persist when navigating between pages
- Graph · Cache · Confidence badges on each response

### Document Upload (Admin only)
- Drag & drop: PDF, XML, DOCX, TXT, JSON, CSV, HTML
- Pipeline: Parse → Chunk → Embed (BAAI) → Store (Qdrant) → NER → Build Graph
- SharePoint recursive ingestion via REST API

### Knowledge Graph (Admin only)
- Automatic entity extraction: contracts, dates, amounts, organizations
- Force-directed visualization with zoom, search, and type filters
- **No Neo4j required** — backed by SQLite graph tables

### Admin Panel
| Tab | Description |
|-----|-------------|
| Overview | Live system health: Qdrant, Graph DB, LLM, Auth |
| Users | List, block/unblock, role management |
| Security | Event log, severity filters, resolve events |
| Rule Engine | Create/toggle/delete RBAC content rules |
| Monitoring | Latency, cache hit rate, hourly query chart |
| Chunks (Qdrant) | Browse chunks grouped by document in collapsible folders |
| Storage Info | SQLite file stats + Qdrant collection status |

### Analytics (Admin only)
- Total queries, avg latency, cache hit rate, confidence scores
- Daily query trend (14 days) + hourly distribution chart

### Settings (Admin only)
- API key management
- Model configuration
- Cache settings
- Security (JWT, RBAC, session timeout)
- Alerts & notifications (toggleable)

---

## Data Storage

| Data | Location |
|------|----------|
| Users, chat logs, security events, rules | `cortexflow.db` — SQLite (project root) |
| Knowledge graph (nodes + edges) | `cortexflow.db` — `graph_nodes` / `graph_edges` tables |
| Document vector embeddings | Qdrant — collection `phase1_documents` |
| Uploaded files | `uploaded_docs/` directory |

**View SQLite data:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('cortexflow.db')
print('Users:'); [print(' ', r) for r in conn.execute('SELECT email, role FROM users')]
print('Graph nodes:', conn.execute('SELECT COUNT(*) FROM graph_nodes').fetchone()[0])
print('Chunks in Qdrant: see http://localhost:6333/dashboard')
conn.close()
"
```

---

## Environment Variables

Copy `.env.example` → `.env` and fill in your values:

```env
SECRET_KEY=your-secret-key-min-32-chars
COHERE_API_KEY=your-cohere-api-key

# Qdrant (default: localhost)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Neo4j (optional — system uses SQLite graph if unavailable)
NEO4J_URI=bolt://localhost:7689
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
```

> ⚠️ `.env` is in `.gitignore` — **never commit it**.

---

## Project Structure

```
├── app/                    FastAPI application
│   ├── api/                Route handlers (auth, admin, rag)
│   ├── models.py           SQLAlchemy ORM models
│   ├── db.py               DB engine (PostgreSQL → SQLite fallback)
│   └── main.py             App entry point + startup warmup
├── services/               AI service layer
│   ├── phase1_rag.py       Vector retrieval (Qdrant)
│   ├── graph_service.py    Knowledge graph (SQLite)
│   ├── graph_rag.py        Hybrid RAG orchestration
│   └── phase1_llm.py       LLM integration (Cohere)
├── core/                   Config + database connectors
├── frontend/               React 18 + TypeScript + Vite
│   └── src/
│       ├── pages/          Landing, Dashboard, Login, SignUp
│       └── components/     ChatInterface, AdminPanel, Analytics, ...
├── cortexflow.db           SQLite database (auto-created)
├── uploaded_docs/          Uploaded document storage
└── requirements.txt        Python dependencies
```
