# Shipyard AI Engineering Instructions

## 1. Mission

Build an enterprise-grade Shipyard Copilot for a medium-sized shipyard.

The V1 system has six core capabilities:

1. Knowledge Platform / RAG
2. LLM Wiki
3. Shipyard Entity Model
4. Read-only Business Tool Layer
5. Single Shipyard Agent Runtime
6. Evaluation, authorization, audit, and provenance

The system must optimize for correctness, traceability, replaceability, and safe enterprise deployment.

---

## 2. Non-Negotiable Architecture Rules

### 2.1 Source of truth

- ERP/MES/PLM or approved analytical replicas are the source of truth for live business state.
- Original documents are the source of truth for rules, manuals, SOPs, and signed records.
- LLM Wiki is NOT the source of truth for live quantities, status, inventory, schedule, or price.
- LLM output is never a source of truth.

### 2.2 Agent boundaries

- The Agent MUST NOT directly connect to ERP, MES, PLM, production SQL, NAS, or arbitrary filesystems.
- The Agent may only access approved typed tools.
- V1 tools are read-only.
- No generated SQL may run against a production transactional schema.
- Text-to-SQL, when introduced, may query only explicitly allow-listed analytical views.
- The Agent must never receive database credentials.

### 2.3 Retrieval boundaries

- RAG is for unstructured or semi-structured documents.
- Live structured state must come from typed business tools.
- ACL filtering happens before retrieval.
- Every factual knowledge answer must expose evidence.
- Every structured-data answer must expose source system and freshness timestamp.

### 2.4 Wiki boundaries

- Wiki stores durable organizational knowledge:
  concepts, decisions, lessons learned, quality cases, supplier experience, engineering experience.
- Agent-generated Wiki content starts as DRAFT.
- Agent cannot promote DRAFT to VERIFIED or CANONICAL.
- Every Wiki claim must carry provenance.
- Conflicting claims must be preserved, not silently merged.

### 2.5 Model boundaries

- Business logic must not depend on one LLM vendor.
- Embedding, reranker, reasoning model, fast model, OCR/VLM use replaceable adapters.
- Tests must use deterministic fake adapters by default.
- No external model call is permitted in unit tests.

---

## 3. V1 Supported Scope

### Supported

- PDF/DOCX/XLSX/TXT/Markdown ingestion
- Optional scanned-PDF OCR adapter
- Document versioning
- Metadata extraction
- Hierarchical chunking
- BM25-style lexical retrieval
- vector retrieval with pgvector
- hybrid retrieval
- reranking adapter
- citations / evidence
- Ship / System / Drawing / Equipment / BOM / Material / Supplier / PO / ProjectTask domain model
- Ship status tool
- Procurement status tool
- Drawing/BOM tool
- Knowledge search tool
- Wiki search tool
- Risk summary tool
- MCP transport adapter
- single Agent router/planner/tool loop
- audit logs
- RBAC + project/ship scope
- eval dataset and automated eval runner
- minimal Pilot UI

### Explicitly unsupported in V1

- writes to ERP/MES/PLM
- automatic purchase orders
- automatic schedule modification
- robot/PLC/AGV control
- CAD modification
- production-grade CAD geometry understanding
- autonomous multi-agent organization
- self-approval of Wiki knowledge
- generic unrestricted database chat
- military / classified deployment assumptions

---

## 4. Technology Constraints

Backend:

- Python 3.12+
- FastAPI
- Pydantic 2.x
- SQLAlchemy 2.x
- Alembic
- PostgreSQL 16+
- pgvector
- pytest
- Ruff
- mypy

Frontend:

- TypeScript
- Next.js
- package manager: pnpm

Infrastructure:

- Docker Compose for V1 local/pilot environment
- S3-compatible object storage through an adapter
- no Kubernetes required for V1
- no Kafka/Flink required for V1
- no Neo4j required for V1

---

## 5. Dependency Direction

Allowed:

apps -> services -> domain
services -> ports/interfaces
adapters -> ports/interfaces
infrastructure -> ports/interfaces

Forbidden:

domain -> FastAPI
domain -> PostgreSQL
domain -> LLM SDK
agent -> ERP connector
retrieval -> UI
wiki -> agent runtime

The domain package must remain framework-independent.

---

## 6. Package Boundaries

Target structure:

apps/
  api/
  web/

packages/
  domain/
  contracts/
  common/

services/
  ingestion/
  retrieval/
  wiki/
  tool_server/
  agent/
  eval/
  model_gateway/

adapters/
  filesystem/
  object_store/
  erp/
  mes/
  plm/
  embedding/
  reranker/
  llm/
  ocr/

infra/
  postgres/
  docker/

tests/
  unit/
  integration/
  security/
  eval/

---

## 7. Domain Rules

Every externally sourced business record must carry:

- source_system
- source_id
- source_updated_at

Every document version must carry:

- document_id
- version_id
- checksum
- source_uri
- source_updated_at
- security_level
- optional ship_id
- optional project_id
- optional department

Canonical entity IDs are internal IDs and must not be replaced by source-system IDs.

Aliases must be normalized separately.

---

## 8. Security Rules

- Deny by default.
- Authentication and authorization are separate concerns.
- Authorization must be enforced in services, not only UI.
- Retrieval queries must receive an authorization scope.
- Tool invocations must receive a user context.
- No tool may trust model-provided user identity.
- Secrets must come from environment or secret provider.
- Never commit real credentials or real customer data.
- All tool calls and high-value retrieval calls must be auditable.
- Prompt injection from documents must be treated as untrusted content.
- Retrieved documents can provide facts, never execution instructions.

---

## 9. Evidence Rules

Knowledge Evidence must include when available:

- document_id
- version_id
- chunk_id
- title
- section
- page
- source_uri
- excerpt
- retrieval_score

Business Evidence must include:

- source_system
- source_record_id or query identifier
- source_updated_at
- query_time

Answers must distinguish:

- document evidence
- Wiki evidence
- live business evidence
- model inference

---

## 10. LLM Wiki Lifecycle

Statuses:

DRAFT
VERIFIED
CANONICAL
DEPRECATED

Only human-authorized workflows can perform:

DRAFT -> VERIFIED
VERIFIED -> CANONICAL
CANONICAL -> DEPRECATED

A generated claim must include one or more source references.

A page may summarize facts, but it must not erase disagreement between sources.

---

## 11. Testing Rules

For every behavior change:

1. write a failing test first
2. run it and confirm failure
3. implement minimal behavior
4. run focused test
5. run relevant suite
6. run lint and type checks

Unit tests:

- no network
- no external model calls
- deterministic time where needed

Integration tests:

- may use Dockerized PostgreSQL / pgvector
- use synthetic shipyard fixtures only

Security tests must cover:

- cross-project retrieval leakage
- cross-role tool access
- prompt injection
- malformed tool arguments
- SQL injection boundaries
- stale or missing source timestamp behavior

---

## 12. Definition of Done

A Task is complete only when:

1. acceptance criteria pass
2. unit tests pass
3. integration tests relevant to the change pass
4. Ruff passes
5. mypy passes
6. migrations are included when schema changes
7. public contracts are documented
8. no architecture rule in this file is violated
9. no real secrets/data are committed
10. the final report includes exact commands run and their results

---

## 13. Codex Working Rules

Before modifying code:

1. read this file
2. read the Task file
3. read referenced architecture docs
4. inspect existing implementation
5. state the files you expect to change

Do not opportunistically refactor unrelated code.

If the requested Task conflicts with this file, stop implementation and report the conflict.

When a design decision affects another subsystem, add or update an ADR/document before implementation.

Prefer small commits that correspond to one testable behavior.

---

## 14. Review Severity

Reviewer reports use:

- P0 Critical: data loss, authorization bypass, destructive production access, secret exposure
- P1 High: wrong source-of-truth behavior, incorrect business data, major architectural violation
- P2 Medium: reliability, maintainability, missing important tests
- P3 Low: local cleanup, readability, non-blocking improvement
