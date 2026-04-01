# CortexFlow AI — Enterprise Knowledge Intelligence Platform

> Production-grade SaaS AI platform combining Hybrid RAG, Knowledge Graphs, Agent Orchestration, Self-Learning, and Zero-Trust Security.

[![Version](https://img.shields.io/badge/version-4.0.0-blue)](.) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](.) [![React](https://img.shields.io/badge/React-18-blue)](.) [![License](https://img.shields.io/badge/license-MIT-gray)](.)

---

## Overview

CortexFlow is a **production-ready enterprise SaaS platform** designed to ChatGPT Enterprise / Palantir-level standards. It enables organisations to extract precise, multi-hop intelligence from their document corpora using a layered AI architecture.

### Core Capabilities

| Capability | Description |
|---|---|
| **Hybrid RAG** | Dense vector search (Qdrant) + sparse BM25 retrieval fused with graph context |
| **Knowledge Graph** | Auto NER → relationship extraction → Neo4j storage → graph-augmented retrieval |
| **Agent Orchestrator** | LangGraph-style query routing: Vector → Graph → SQL → Calculator → Summarizer |
| **Multi-hop Reasoning** | Decomposes complex queries into sub-questions, re-ranks, and fuses results |
| **Self-Learning** | Feedback loop improves retrieval without fine-tuning; session memory for context-aware follow-ups |
| **Real-time Streaming** | SSE token-by-token response streaming with confidence scores and source citations |
| **Zero-Trust Security** | JWT RBAC, prompt injection detection, document-level filtering, dynamic rule engine |
| **Admin Intelligence** | User risk scoring, security event tracking, live analytics, Knowledge Graph UI |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Frontend (React + Vite + Tailwind)              │
│                                                                       │
│  Landing → Auth (Login/Signup/ForgotPwd) → Dashboard                │
│  ├── Chat          (streaming, markdown, confidence, sources)        │
│  ├── Upload        (Phase 1–3 ETL pipeline)                          │
│  ├── Analytics     (real-time metrics from DB)                       │
│  ├── Knowledge Graph UI  (force-directed graph, search)              │
│  ├── Admin Panel   (users, security events, rule engine, monitoring) │
│  └── Settings      (API keys, model, cache, rate limits)             │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTPS + JWT Bearer
┌───────────────────────────▼─────────────────────────────────────────┐
│                       FastAPI Backend (v4.0)                         │
│                                                                       │
│  /auth/*         — signup, login, refresh, user management           │
│  /ask            — query with RBAC, security scan, full response      │
│  /ask/stream     — SSE streaming endpoint                            │
│  /feedback       — thumbs up/down for self-learning                  │
│  /chat/history   — per-user chat history                             │
│  /upload         — document ingestion (Phase 1–3)                   │
│  /admin/*        — rules CRUD, security events, analytics, graph     │
│  /health         — system status                                      │
└──────┬────────────┬───────────────┬─────────────────┬───────────────┘
       │            │               │                 │
┌──────▼──┐  ┌──────▼──┐  ┌────────▼──────┐  ┌──────▼──────────────┐
│ Qdrant  │  │  Neo4j  │  │  PostgreSQL   │  │  Redis (optional)   │
│ Vectors │  │  Graph  │  │  Users/Logs   │  │  Semantic Cache     │
└─────────┘  └─────────┘  └───────────────┘  └─────────────────────┘
```

### Query Processing Pipeline

```
User Query
    │
    ▼
1. JWT Authentication + RBAC check
    │
    ▼
2. Security scan (prompt injection, rate limit, data leakage)
    │
    ▼
3. Self-Learning: enrich query with feedback signals + session context
    │
    ▼
4. Agent Orchestrator — classify & route
    ├── DocumentSearchTool  → Qdrant vector retrieval (with RBAC filter)
    ├── GraphQueryTool      → Neo4j entity + relationship lookup
    ├── CalculatorTool      → arithmetic extraction
    └── SummarizationTool   → context compression for long docs
    │
    ▼
5. Multi-hop decomposition + cross-encoder re-ranking
    │
    ▼
6. Context Fusion  (Graph + Vector + Calculator merged)
    │
    ▼
7. LLM generation (Cohere / OpenAI)
    │
    ▼
8. Response: answer + sources + confidence + query_type
    │
    ▼
9. Store chat log → update user activity → cache result
    │
    ▼
10. Stream tokens to UI via SSE
```

---

## Feature Set

### ✅ Phase 1 — Baseline RAG
- [x] Multi-format ingestion: PDF, XML, DOCX, TXT, JSON, CSV, HTML, PPTX, MD
- [x] Semantic embeddings: `BAAI/bge-large-en-v1.5` (1024-dim)
- [x] Vector similarity search: Qdrant with RBAC payload filtering
- [x] LLM answer generation: Cohere `command-r7b-12-2024`

### ✅ Phase 2 — Intelligence Layer
- [x] Query classification: fact, summary, comparison, analytical
- [x] Multi-hop query decomposition on conjunctive questions
- [x] Cross-encoder re-ranking: `ms-marco-MiniLM-L-6-v2`
- [x] Semantic caching (in-memory; Redis-ready)
- [x] Role-based access control at retrieval time

### ✅ Phase 3 — Graph RAG / Knowledge Graph Pipeline

#### Named Entity Recognition
- [x] Contract entity extraction (numbers, IDs, parties)
- [x] Date entity extraction (start, end, effective dates)
- [x] Amount entity extraction (dollar values, currency)
- [x] Organization entity extraction (company names, counterparties)

#### Relationship Extraction
- [x] `CONTRACT → STARTS_ON → DATE`
- [x] `CONTRACT → ENDS_ON → DATE`
- [x] `CONTRACT → ISSUED_BY → ORGANIZATION`
- [x] `CONTRACT → HAS_AMOUNT → AMOUNT`
- [x] `DOCUMENT → MENTIONS → ENTITY`
- [x] Bidirectional multi-hop traversal

#### Automatic Graph Generation
- [x] Entity deduplication and normalization
- [x] Auto-stored in Neo4j on every document upload
- [x] Chunk-to-node linking: vector chunk ↔ graph entity
- [x] Hybrid retrieval: vector search + graph expansion at query time

### ✅ Phase 4 — Agent Orchestration
- [x] **AgentOrchestrator** — LangGraph-style conditional edge routing
- [x] **DocumentSearchTool** — Qdrant vector retrieval
- [x] **GraphQueryTool** — Neo4j entity and relationship queries
- [x] **SummarizationTool** — context compression for long documents
- [x] **CalculatorTool** — arithmetic extraction from query text
- [x] Context Fusion: Graph + Vector + Calculator merged before LLM

### ✅ Phase 5 — Self-Learning System (without fine-tuning)
- [x] **Chat log storage** — all Q&A stored in PostgreSQL
- [x] **Feedback loop** — thumbs up/down updates confidence modifiers
- [x] **Session memory** — last 6 turns kept for context-aware follow-ups
- [x] **Query expansion** — frequently downvoted queries auto-expanded
- [x] **User context hints** — returning users get improved responses
- [x] **Query optimization** — feedback-adjusted confidence scores

### ✅ Phase 6 — Enterprise Security (Zero-Trust)
- [x] **JWT authentication** with 24h access / 7d refresh tokens
- [x] **Prompt injection detection** — 20+ regex patterns
- [x] **Data leakage detection** — PII and mass-export patterns
- [x] **Scraping detection** — mass extraction attempts
- [x] **Rate limiting** — sliding window per user (60 req/min default)
- [x] **Dynamic rule engine** — admin creates regex-based rules (block/warn/restrict/log)
- [x] **User risk scoring** — 0–100 score, low/medium/high/critical levels
- [x] **Document-level RBAC** — access_roles payload filter in Qdrant
- [x] **Security event logging** — all threats stored in PostgreSQL
- [x] **Audit log** — full query audit trail

### ✅ Phase 7 — Admin Panel
- [x] **System Overview** — Qdrant, Neo4j, LLM, PostgreSQL live health
- [x] **User Management** — list, block, unblock, role assignment, risk indicator
- [x] **Security Dashboard** — threat log, severity filter, resolve events, stats
- [x] **Dynamic Rule Engine** — create/edit/delete/toggle rules (persisted in DB)
- [x] **Model Monitoring** — latency, cache hit rate, graph usage, confidence
- [x] **Knowledge Graph UI** — force-directed graph visualization, search, entity drill-down

### ✅ Phase 8 — Analytics Dashboard
- [x] KPI cards: total queries, avg latency, cache hit rate, graph usage, confidence, users
- [x] Daily query trend (14 days) — line chart
- [x] Cache hit rate trend — line chart
- [x] Hourly query distribution — bar chart
- [x] Retrieval quality by query type — horizontal bar

### ✅ Phase 9 — Real-time Features
- [x] **SSE streaming** — `/ask/stream` endpoint for token-by-token output
- [x] **Simulated streaming** — smooth character-reveal in Chat UI
- [x] **Notifications panel** — security alerts + system status
- [x] **Alert badge** — unread count on admin sidebar item
- [x] **Auto-polling** — 30s interval for new security events (admin)

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Docker (for databases)
- Cohere API key (free at [cohere.com](https://cohere.com))

### 1. Clone & Configure

```bash
git clone <repo-url>
cd Temporal-Intelligence-AI-Platform

# Create .env
cp .env.example .env
# Edit .env and set: COHERE_API_KEY, SECRET_KEY
```

### 2. Start Databases (Docker)

```bash
# Qdrant (vector DB)
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant

# Neo4j (knowledge graph)
docker run -d --name neo4j \
  -p 7689:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/password123 \
  neo4j:5

# PostgreSQL (users, logs, rules)
docker run -d --name postgres \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=password123 \
  -e POSTGRES_DB=cortexflow_db \
  postgres:15
```

### 3. Backend Setup

```bash
pip install -r requirements.txt

# Initialize database tables + seed default rules
PYTHONPATH=. python -c "from app.db import init_db; init_db()"

# Ingest sample documents into Qdrant + Neo4j
PYTHONPATH=. python scripts/ingest.py

# Start FastAPI server
PYTHONPATH=. python run.py
# → API at http://localhost:8000
# → Docs at http://localhost:8000/docs
```

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
# → UI at http://localhost:5173
```

### 5. Create Admin Account

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@cortexflow.ai","password":"Admin123!","name":"Admin","role":"admin"}'
```

---

## API Reference

### Authentication

```bash
# Sign Up
POST /auth/signup
{"email":"user@example.com","password":"pass","name":"Jane","role":"client"}

# Login
POST /auth/login
{"email":"user@example.com","password":"pass"}
# Returns: access_token, refresh_token, user

# Refresh token
POST /auth/refresh
{"refresh_token":"<token>"}

# Get current user
GET /auth/me  [Bearer token]
```

### Chat & Query

```bash
# Query (full response with sources + confidence)
POST /ask  [Bearer token]
{"question":"Which contracts started in 2019?","role":"user"}
# Returns: answer, graph_used, confidence, query_type, sources[], latency_ms, chat_log_id

# Streaming (SSE)
GET /ask/stream?question=<q>&role=user  [Bearer token]
# Server-Sent Events: meta → tokens → done

# Submit feedback
POST /feedback  [Bearer token]
{"chat_log_id":"<id>","feedback":"positive"}

# Chat history
GET /chat/history?limit=50  [Bearer token]
```

### Upload

```bash
POST /upload  [Bearer token]  multipart/form-data
# Supported: .pdf .xml .docx .txt .csv .json .html .pptx .md
# Returns: status, filename, message, entities
```

### Admin

```bash
# Rules CRUD
GET    /admin/rules            [admin]
POST   /admin/rules            [admin]  {"name","pattern","action","role"}
PUT    /admin/rules/{id}       [admin]
DELETE /admin/rules/{id}       [admin]
PATCH  /admin/rules/{id}/toggle [admin]

# Security
GET  /admin/security/events    [admin]
GET  /admin/security/stats     [admin]
PATCH /admin/security/events/{id}/resolve  [admin]

# Analytics
GET /admin/analytics           [admin]
GET /admin/analytics/users     [admin]

# Knowledge Graph
GET /admin/graph/data          [admin]  ?limit=200
GET /admin/graph/search?keyword=<kw>   [admin]
GET /admin/graph/entity/{name} [admin]

# System health
GET /admin/system/health       [admin]

# User management
GET  /auth/users               [admin]
POST /auth/users/{id}/block    [admin]
POST /auth/users/{id}/unblock  [admin]
PUT  /auth/users/{id}/role     [admin]
```

---

## Configuration

Edit `core/config.py` or set environment variables in `.env`:

```env
# Database
NEO4J_URI=bolt://localhost:7689
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
QDRANT_HOST=localhost
QDRANT_PORT=6333

# LLM
COHERE_API_KEY=sk_...
COHERE_MODEL=command-r7b-12-2024
OPENAI_API_KEY=sk-...     # optional

# Security
SECRET_KEY=change-me-in-production   # JWT signing key

# App
API_HOST=0.0.0.0
API_PORT=8000
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

---

## Project Structure

```
├── app/                          # FastAPI application
│   ├── api/
│   │   ├── routes.py            # /ask, /stream, /upload, /feedback, /chat/history
│   │   ├── auth_routes.py       # /auth/* endpoints
│   │   ├── admin_routes.py      # /admin/* endpoints (rules, security, analytics, graph)
│   │   └── schemas.py           # Pydantic request/response models
│   ├── services/
│   │   ├── auth_service.py      # User registration, auth, block/unblock
│   │   └── rag_service.py       # RAG orchestration (calls agent orchestrator)
│   ├── core/
│   │   ├── security.py          # JWT utilities, password hashing
│   │   └── config.py            # Settings (pydantic-settings)
│   ├── models.py                 # SQLAlchemy: User, ChatLog, SecurityEvent, Rule, etc.
│   ├── db.py                     # PostgreSQL engine + session
│   ├── dependencies.py           # JWT middleware, role guards
│   └── main.py                   # FastAPI app + startup + router wiring
│
├── services/                     # Business logic
│   ├── agent_orchestrator.py    # LangGraph-style agent routing pipeline
│   ├── self_learning.py         # Feedback loop, session memory, query optimization
│   ├── security_service.py      # Prompt injection detection, rate limiting, risk scoring
│   ├── phase1_rag.py            # Core RAG orchestrator (Phase 1+2+3)
│   ├── phase1_pipeline.py       # Document parsing, chunking, access roles
│   ├── phase1_llm.py            # LLM service (Cohere/OpenAI)
│   ├── graph_rag.py             # Hybrid retrieval (vector + graph)
│   ├── graph_service.py         # Neo4j: entity extraction, storage, queries
│   ├── embedding_service.py     # BAAI sentence embeddings
│   ├── query_classifier.py      # Query type classification
│   ├── reranker.py              # Cross-encoder re-ranking
│   ├── multihop.py              # Multi-hop query decomposition
│   └── cache_service.py         # Semantic cache (in-memory / Redis-ready)
│
├── core/
│   ├── config.py                # App settings (env vars)
│   └── database.py              # Qdrant + Neo4j connection helpers
│
├── frontend/                    # React application
│   └── src/
│       ├── pages/
│       │   ├── Landing.tsx      # Public landing page (hero, features, demo, pricing)
│       │   ├── Login.tsx        # JWT login form
│       │   ├── SignUp.tsx       # Registration with role selection
│       │   ├── ForgotPassword.tsx
│       │   └── Dashboard.tsx    # Main app shell (topbar, notifications)
│       └── components/
│           ├── Sidebar.tsx          # Nav with admin-only graph + alert badge
│           ├── ChatInterface.tsx    # Streaming chat, feedback, history
│           ├── DocumentUpload.tsx   # Phase 1–3 upload + ETL display
│           ├── AdminPanel.tsx       # 5-tab admin (real API data)
│           ├── Analytics.tsx        # Live analytics from DB
│           ├── KnowledgeGraphUI.tsx # Force-directed graph visualization
│           ├── NotificationsPanel.tsx # Real-time alerts panel
│           ├── Settings.tsx         # API keys, model, cache, security config
│           └── RoleSelector.tsx     # Role switcher for chat
│
├── scripts/
│   └── ingest.py               # Batch document ingestion
├── sample_data/                # Sample XML contracts
├── uploaded_docs/              # User-uploaded documents
├── requirements.txt
└── README.md
```

---

## Security Architecture

### Zero-Trust Layers

1. **Transport** — HTTPS enforced in production; CORS restricted to known origins
2. **Authentication** — JWT HS256 with 24h expiry; refresh token rotation
3. **Authorization** — Role-based access control: `public | user | client | admin`
4. **Document-level** — Qdrant payload filter enforces `access_roles` per vector chunk
5. **Query-time** — Dynamic rule engine scans every query against admin-defined patterns
6. **Threat detection** — Prompt injection, data leakage, scraping, and SQL injection patterns
7. **Rate limiting** — Sliding window (60 req/min per user) with configurable threshold
8. **Risk scoring** — Users scored 0–100; suspicious activity escalates risk level
9. **Audit trail** — All queries, uploads, and security events logged to PostgreSQL

### Security Event Types

| Type | Severity | Action |
|---|---|---|
| Prompt injection | High | Block query + log event + update risk |
| Data leakage attempt | High | Block query + log event + update risk |
| Mass scraping | Medium | Warn + log |
| Rate limit exceeded | Medium | Reject + log |
| Unauthorized access | High | Reject + log |

---

## Performance

| Operation | Latency |
|---|---|
| Cache hit (in-memory) | ~5ms |
| Vector search (Qdrant) | ~50–100ms |
| Graph query (Neo4j) | ~20–60ms |
| Re-ranking (cross-encoder) | ~10–20ms |
| LLM generation (Cohere) | ~500ms–2s |
| Full end-to-end (no cache) | ~600ms–2.5s |

---

## Troubleshooting

```bash
# Qdrant not connecting
docker ps | grep qdrant
docker restart qdrant

# Neo4j not connecting
docker logs neo4j
# Default: neo4j / password123

# PostgreSQL connection refused
docker logs postgres
# Ensure POSTGRES_DB=cortexflow_db

# COHERE_API_KEY missing
echo "COHERE_API_KEY=sk_..." >> .env

# JWT decode errors
# Verify SECRET_KEY in .env hasn't changed between restarts

# Frontend can't reach backend
# Check vite.config.ts proxy points to http://localhost:8000
```

---

## Roadmap

- [ ] Fine-tuning with LoRA (deferred — Phase 10)
- [ ] SharePoint / Google Drive / S3 connectors (Phase 2 Upload)
- [ ] Redis semantic cache (replace in-memory CacheService)
- [ ] WebSocket for true bidirectional streaming
- [ ] Langfuse / observability integration
- [ ] Multi-tenant workspace isolation
- [ ] SAML / SSO enterprise authentication

---

## Resources

- [Cohere API Docs](https://docs.cohere.com)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [Neo4j Docs](https://neo4j.com/docs/)
- [FastAPI Guide](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev)

---

## License

MIT License — See LICENSE file

## Support

- GitHub Issues: [cortexflow/ai/issues](https://github.com/cortexflow/ai/issues)
- Email: support@cortexflow.ai
- Docs: https://cortexflow.ai/docs

---

**Built with FastAPI · React · Qdrant · Neo4j · PostgreSQL · Cohere · spaCy**

Last Updated: 2026-04-01 | Version: 4.0.0
