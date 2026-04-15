# CortexFlow AI — Enterprise Knowledge Intelligence Platform

> Production-grade AI platform combining Hybrid RAG, Knowledge Graphs, Website Crawling, Multi-Source Ingestion, Role-Based Access Control, and a full Admin Dashboard — built by Team Nitco Inc.

[![Version](https://img.shields.io/badge/version-6.1.0-blue)](.) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](.) [![React](https://img.shields.io/badge/React-18-blue)](.) [![Qdrant](https://img.shields.io/badge/Qdrant-1.x-brightgreen)](.) [![License](https://img.shields.io/badge/license-MIT-gray)](.)

---

## Architecture

```
Browser (React 18 + Vite + TypeScript)
    │
    ▼
FastAPI Backend (Python 3.12)
    ├── Ingestion Layer
    │     ├── Local file upload   — PDF, DOCX, PPTX, CSV, TXT, JSON, HTML, MD
    │     ├── SharePoint          — MS Graph delta sync + webhooks (event-driven)
    │     └── Website Crawler     — BFS deep-crawl, sitemap seeding, JS rendering (Playwright optional)
    │
    ├── Processing Layer
    │     ├── Phase 1 · RAG           — Qdrant vector search + BAAI/bge-large-en-v1.5
    │     ├── Phase 2 · Intelligence  — Hybrid search (BM25 + vector), query classifier, reranker, cache
    │     └── Phase 3 · Graph RAG     — SQLite knowledge graph + multi-hop retrieval
    │
    ├── Scheduler Service           — centralized multi-level scheduling (10min/2hr/24hr)
    ├── Storage Service             — MinIO / S3 (primary) + local filesystem fallback
    └── Cache Service               — Redis (persistent, survives restarts) + in-memory fallback
         │
         ├── PostgreSQL  (primary)  — users, chat logs, rules, security events (SQLite fallback)
         ├── Redis       (optional) — LLM/query cache persistence, sessions
         ├── Qdrant      (port 6333)— 1024-dim vector embeddings (bge-large), all sources unified
         └── MinIO       (optional) — raw files, HTML snapshots, processed text (S3-compatible)
```

**LLM:** Cohere `command-r7b-12-2024` via `COHERE_API_KEY` · OpenAI `gpt-4o` fallback
**Embedding:** `BAAI/bge-large-en-v1.5` — 335M params, 1024-dim
**Graph DB:** SQLite (primary), Neo4j optional at `bolt://localhost:7687`
**Collection:** Single Qdrant collection `phase1_documents` — all sources, unified metadata

---

## Data Sources

| Source | How it works | Metadata |
|--------|-------------|----------|
| **Local files** | Upload → background ingest queue → chunk → embed → Qdrant | `source_type=file` |
| **SharePoint** | MS Graph delta sync + webhooks → auto-ingest on change | `source_type=sharepoint` |
| **Website** | BFS crawl → sitemap seed → extract → chunk → embed | `source_type=website` |

All sources share a unified Qdrant schema with fields:
`source_type`, `source_name`, `url`, `page_type`, `section`, `file_name`,
`content_hash`, `version`, `timestamp`, `chunk_id`, `tenant_id`

---

## Quick Start

### Step 1 — Start Infrastructure

```bash
# Qdrant (vector store) — required
docker start qdrant_cf
# If new: docker run -d -p 6333:6333 --name qdrant_cf qdrant/qdrant

# Optional: PostgreSQL
docker start postgres_cf

# Optional: Redis (for persistent cache)
docker start redis_cf
# If new: docker run -d -p 6379:6379 --name redis_cf redis:7-alpine

# Optional: MinIO (for object storage)
docker start minio_cf
# If new: docker run -d -p 9000:9000 -p 9001:9001 --name minio_cf \
#   -e MINIO_ROOT_USER=admin -e MINIO_ROOT_PASSWORD=password123 minio/minio server /data --console-address :9001
```

### Step 2 — Configure .env

```env
# Required
COHERE_API_KEY=your-cohere-key
SECRET_KEY=change-me-in-production

# Optional: PostgreSQL (falls back to SQLite if not set)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password123
POSTGRES_DB=cortexflow_db

# Optional: Redis (in-memory cache if not set — does not survive restarts)
REDIS_URL=redis://localhost:6379/0

# Optional: MinIO / S3 (local filesystem if not set)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=password123
MINIO_BUCKET=cortexflow

# Optional: SharePoint
SHAREPOINT_TENANT_ID=your-tenant-id
SHAREPOINT_CLIENT_ID=your-client-id
SHAREPOINT_CLIENT_SECRET=your-secret
SHAREPOINT_NOTIFICATION_URL=https://your-public-host.com

# Optional: OpenAI fallback LLM
OPENAI_API_KEY=sk-...
```

### Step 3 — Start Backend

```bash
cd /workspaces/Temporal-Intelligence-AI-Platform
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Step 4 — Start Frontend

```bash
cd frontend
npm install
npm run dev
# Opens on http://localhost:5173
```

---

## Features

### Admin Panel
- **Upload Documents** — PDF, DOCX, PPTX, CSV, TXT, JSON, HTML, MD; up to 500 MB
- **SharePoint** — Connect any SharePoint site; delta sync + webhooks; auto-indexed
- **Website Scraper** — Paste any org URL; BFS deep-crawl with sitemap seeding; incremental updates; Playwright JS rendering (when installed)
- **Chunks / Ingestion Status** — Live view of all indexed chunks; ingestion progress for uploads and SharePoint
- **Knowledge Graph** — Entity relationships from all documents
- **Analytics** — Query volume, confidence trends, top questions
- **Settings** — API keys, model config, rules management
- **Scheduler** — Auto re-crawl schedules (via `/admin/scheduler/status`)

### Chat Interface
- Role-aware answers (user = warm, admin = technical with citations)
- Session history with title and timestamp
- Stop button — cancels in-flight request and visual streaming animation
- Rate limit display with countdown
- Source attribution with confidence scores
- Navigation support — provides direct URLs and step-by-step navigation from indexed website content

### Scheduler (automatic updates)
| Priority | Sources | Interval |
|----------|---------|----------|
| High | Homepage, service pages | Every 10 minutes |
| Medium | Docs, product pages | Every 2 hours |
| Low | Blogs, static pages | Every 24 hours |

Admins can trigger manual crawls via:
```
POST /admin/scheduler/trigger    { "source_id": "..." }
POST /admin/scheduler/pause/{id}
POST /admin/scheduler/resume/{id}
```

---

## Storage Architecture

```
Document uploaded / page crawled
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│  MinIO / S3         Raw bytes (PDF, DOCX, HTML snapshot)        │
│  (object storage)   Unlimited scale, cheap, no DB overload      │
├─────────────────────────────────────────────────────────────────┤
│  PostgreSQL         Metadata: users, chat logs, rules,          │
│  (relational DB)    ingestion jobs, audit logs                  │
├─────────────────────────────────────────────────────────────────┤
│  Qdrant             Embeddings: all chunks from all sources     │
│  (vector DB)        Single collection: phase1_documents         │
├─────────────────────────────────────────────────────────────────┤
│  Redis              LLM cache, query cache, sessions            │
│  (cache)            Persists across server restarts             │
└─────────────────────────────────────────────────────────────────┘
```

**Fallback chain (dev/offline):**
- PostgreSQL unavailable → SQLite
- Redis unavailable → in-memory LRU cache (lost on restart)
- MinIO unavailable → local `uploaded_docs/` directory

---

## API Reference

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ask` | Query the knowledge base |
| GET | `/chat/history` | Session history |

### Upload
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload and ingest a file |
| POST | `/upload/batch` | Upload multiple files |

### SharePoint
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sharepoint/connect` | Connect SharePoint site |
| POST | `/sharepoint/disconnect` | Disconnect site |
| GET | `/sharepoint/status` | Connection status |

### Website Scraper
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/website/connect` | Start deep-crawl of org URL |
| POST | `/website/disconnect` | Stop crawl (optional: delete vectors) |
| GET | `/website/status` | All crawl connections |
| GET | `/website/status/{id}` | Single connection status |
| POST | `/website/refresh/{id}` | Trigger incremental re-crawl |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/scheduler/status` | Scheduler status + all sources |
| POST | `/admin/scheduler/trigger` | Manual crawl trigger |
| POST | `/admin/scheduler/pause/{id}` | Pause source |
| POST | `/admin/scheduler/resume/{id}` | Resume source |
| GET | `/admin/cache/status` | Cache backend + hit rate |
| GET | `/admin/storage/status` | Storage backend (MinIO vs local) |
| GET | `/admin/ingest-jobs` | Live ingestion queue status |
| GET | `/admin/system/health` | System health |

---

## Project Structure

```
├── app/
│   ├── api/
│   │   ├── routes.py           # /ask, /upload, /health
│   │   ├── admin_routes.py     # /admin/* endpoints (rules, security, scheduler, cache)
│   │   ├── auth_routes.py      # /auth/login, /auth/signup
│   │   ├── sharepoint_routes.py# /sharepoint/connect, /disconnect, /status
│   │   └── website_routes.py   # /website/connect, /disconnect, /status, /refresh
│   ├── main.py                 # FastAPI app, startup hooks
│   └── db.py                   # PostgreSQL + SQLite fallback
│
├── services/
│   ├── agent_orchestrator.py   # Full RAG pipeline (retrieve → rerank → build → LLM)
│   ├── website_crawler.py      # BFS crawler, JS rendering, stat/people extraction
│   ├── scheduler_service.py    # Multi-level scheduling, source registry, priority queue
│   ├── storage_service.py      # MinIO / S3 + local filesystem abstraction
│   ├── cache_service.py        # Redis + in-memory LRU cache with TTL
│   ├── sharepoint_service.py   # MS Graph delta sync + webhooks
│   ├── hybrid_search.py        # BM25 + vector RRF fusion
│   ├── document_reader.py      # Exact line/full-doc reading (local + Qdrant)
│   ├── ingest_queue.py         # Background ingest queue
│   └── phase1_llm.py           # Cohere + OpenAI provider chain
│
├── frontend/src/components/
│   ├── ChatInterface.tsx        # Chat with session history + stop button
│   ├── AdminPanel.tsx           # Admin dashboard with live ingestion status
│   ├── WebsiteScraper.tsx       # Website crawl UI with progress bar
│   ├── SharePoint.tsx           # SharePoint connection management
│   ├── DocumentUpload.tsx       # File upload with pipeline view
│   └── Sidebar.tsx              # Navigation (Chat, Upload, SharePoint, Website, Admin)
│
├── core/
│   └── config.py               # Settings (Postgres, Redis, Qdrant, MinIO, Cohere, SharePoint)
│
└── CHANGELOG.md                # Version history
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COHERE_API_KEY` | Yes | — | Cohere LLM API key |
| `SECRET_KEY` | Yes | `change-me` | JWT signing secret |
| `REDIS_URL` | No | `""` | Redis URL; empty = in-memory cache |
| `MINIO_ENDPOINT` | No | `""` | MinIO endpoint; empty = local storage |
| `MINIO_ACCESS_KEY` | No | `""` | MinIO access key |
| `MINIO_SECRET_KEY` | No | `""` | MinIO secret key |
| `MINIO_BUCKET` | No | `cortexflow` | MinIO bucket name |
| `POSTGRES_HOST` | No | `localhost` | PostgreSQL host |
| `POSTGRES_PASSWORD` | No | `password123` | PostgreSQL password |
| `OPENAI_API_KEY` | No | `""` | OpenAI fallback LLM |
| `SHAREPOINT_TENANT_ID` | No | `""` | Azure AD tenant for SharePoint |
| `SHAREPOINT_CLIENT_ID` | No | `""` | SharePoint app client ID |
| `SHAREPOINT_CLIENT_SECRET` | No | `""` | SharePoint app client secret |
| `QDRANT_HOST` | No | `localhost` | Qdrant host |
| `QDRANT_PORT` | No | `6333` | Qdrant port |

---

## Changelog

See [CHANGELOG.md](./CHANGELOG.md) for full version history.

---

## Team

Built by **Nitco Inc.** — Enterprise AI Solutions
