# CortexFlow AI — Guardrails & Safety Rules

This document describes every layer of protection built into the platform: content filtering, access control, prompt security, and operational limits. All guardrails are enforced server-side and cannot be bypassed from the frontend.

---

## 1. Role-Based Access Control (RBAC)

### User Roles

| Role | Capabilities |
|------|-------------|
| `admin` | Full access — documents, admin panel, error logs, user management |
| `user` | Chat only — answers summarized to 150 words, no source citations, no admin routes |
| `public` | Unauthenticated — blocked from all routes that touch documents or user data |

### Enforcement Points

- **JWT token**: every protected route calls `get_current_user()` → decodes role from signed JWT
- **`require_admin` dependency**: applied to every `/admin/*` route — 403 if role is not `admin`
- **Document access_roles**: each Qdrant chunk carries an `access_roles` payload field
  - Default at ingest: `["admin"]` — admin-only
  - Promoted by admin via `PUT /admin/document/access`
  - RAG queries filter on `access_roles` → users never see admin-only chunks
- **Verbatim document read**: `DocumentLineReaderTool` calls `_check_document_access()` before serving any line or full file — checks Qdrant `access_roles` for the requesting user's role

---

## 2. Content Guardrail Rules (Rule Engine)

Rules are stored in the `rules` table and applied in `POST /ask` before the query reaches the AI.

### Default Seeded Rules

| Rule Name | Pattern | Action | Applies To |
|-----------|---------|--------|------------|
| Block PII queries | `ssn\|social.security\|passport.number\|date.of.birth` | **block** | public |
| Warn on financial PII | `salary\|compensation\|credit.card\|bank.account` | **warn** | public |
| Admin-only confidential | `confidential\|restricted\|internal.only\|top.secret` | **restrict** | user |
| Block prompt injection | `ignore.previous\|forget.everything\|jailbreak\|DAN\b` | **block** | public |
| Log SQL-like queries | `DROP TABLE\|DELETE FROM\|UNION SELECT` | **log** | public |

### Rule Actions

| Action | Behaviour |
|--------|-----------|
| `block` | Query is rejected immediately; error returned to client; security event logged |
| `warn` | Query proceeds but a warning is prepended to the response |
| `restrict` | Query is blocked for `user` role; allowed for `admin` |
| `log` | Query proceeds; a security event is written to the `security_events` table |

### Managing Rules

Admins can create, toggle, and delete rules via the **Rule Engine** tab in the Admin Panel, or via the API:

```bash
# Create a rule
POST /admin/rules
{
  "name": "Block competitor mentions",
  "pattern": "competitor_name|rival_brand",
  "action": "block",
  "role": "public",
  "active": true
}

# Toggle a rule on/off
PUT /admin/rules/{id}  { "active": false }

# Delete a rule
DELETE /admin/rules/{id}
```

---

## 3. Prompt Injection Protection

### Detection Patterns (always active, regardless of rules table)

The following patterns are flagged in the Rule Engine seed data and are also validated in `_seed_default_rules()` at startup:

- `ignore.previous` / `forget.everything` — classic prompt override attempts
- `jailbreak` — generic jailbreak keyword
- `DAN` — "Do Anything Now" jailbreak variant

### Additional Defences

- **Role is JWT-sourced, never client-sourced**: even if a client sends `role: admin` in the request body, the role is always taken from the decoded, server-signed JWT — never from the request payload
- **Context separation**: system prompt, document context, and user query are always injected as separate fields to the LLM — never concatenated into a single string that could be overridden

---

## 4. Document Sensitivity & Access

### Auto-Classification at Ingest

Every uploaded document is automatically classified by `MetadataExtractor` (no hardcoding):

| Sensitivity Level | Trigger Signals | Default Access |
|-------------------|-----------------|----------------|
| `high` | Contract, agreement, confidential | `["admin"]` |
| `medium` | Internal report, policy | `["admin"]` |
| `low` | Public release, press release | `["public","user","admin"]` |

The classification is stored per-chunk in Qdrant payload and as a graph node in Neo4j.

### Overriding Access

```bash
# Promote a document to user-visible
PUT /admin/document/access
{ "filename": "annual_report_2024.pdf", "access_roles": ["user","admin"] }

# Lock a document back to admin-only
PUT /admin/document/access
{ "filename": "annual_report_2024.pdf", "access_roles": ["admin"] }

# Check current access
GET /admin/document/access?filename=annual_report_2024.pdf
```

---

## 5. Upload Guardrails

### Allowed File Types

```
.pdf  .xml  .txt  .docx  .json  .csv  .html  .pptx  .md
```

All other extensions are rejected with HTTP 400 before any processing occurs.

### Size Limit

- Default: **10 MB** per file (configurable via `MAX_UPLOAD_SIZE` env var)
- Folder batch uploads enforce the limit per-file

### Filename Sanitisation

- Folder-uploaded files use `__` as a path separator (e.g. `New folder__Q1_Report.pdf`)
- No shell characters or path traversal sequences are allowed in filenames

---

## 6. Authentication Guardrails

- JWT secret is read from `SECRET_KEY` environment variable — no default in production
- Token expiry: **60 minutes** (configurable)
- Blocked users (`is_active=False`) are rejected at the auth dependency layer even with a valid token
- All failed login attempts are written to `security_events` table with severity `warning`

---

## 7. Operational Limits

| Limit | Value | Where Configured |
|-------|-------|-----------------|
| Max upload size | 10 MB | `core/config.py → max_upload_size` |
| Max chat context | 12,000 chars | `core/config.py → chatbot_max_context_chars` |
| Memory turns | 6 | `core/config.py → chatbot_memory_turns` |
| Max sources per response | 8 | `core/config.py → chatbot_max_sources` |
| User answer word limit | 150 words | `app/api/routes.py` |
| Graph entity search limit | 50 results per entity | `services/graph_service.py` |
| Cross-doc entity scan limit | 20 entities max | `services/graph_service.py` |
| SharePoint system folder skip | Forms, _private, Attachments | `app/api/admin_routes.py` |

---

## 8. Error & Audit Logging

All guardrail violations, auth failures, and system errors are captured in two places:

| Log | Location | Format | Contains |
|-----|----------|--------|---------|
| Error log | `logs/error_log.jsonl` | JSON Lines | timestamp, level, source, exception, traceback, request_id, user, path |
| Security events | `cortexflow.db → security_events` | SQLite rows | event_type, severity, description, user, IP, timestamp |

### Accessing Logs

```bash
# Tail errors in real-time
tail -f logs/error_log.txt

# Query via API (admin token required)
GET /admin/errors?limit=50&level=ERROR
GET /admin/errors/stats

# Security events in Admin Panel → Security tab
```

---

## 9. Adding New Guardrails

The Rule Engine is open for extension without modifying existing code (Open/Closed Principle):

1. **UI**: Admin Panel → Rule Engine tab → "New Rule"
2. **API**: `POST /admin/rules` with `name`, `pattern`, `action`, `role`, `active`
3. **Code**: Add new patterns to `_seed_default_rules()` in `app/main.py` — only runs if the rules table is empty (first boot)

New domain profiles for metadata sensitivity classification can be added to `DOMAIN_PROFILES` in `services/metadata_extractor.py` — no other code changes needed.
