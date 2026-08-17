# Shipyard AI V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe, attributable, read-mostly Shipyard Copilot V1 with RAG, LLM Wiki, typed business tools, a single Agent runtime, security controls, and offline evals.

**Architecture:** The implementation separates knowledge, business tools, Agent runtime, and governance. Live structured state remains in approved business sources and is exposed only through typed read-only tools; unstructured knowledge is retrieved with ACL-aware hybrid retrieval; durable synthesized knowledge is stored in a governed Wiki; one bounded Agent composes these capabilities.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2.x, SQLAlchemy 2.x, Alembic, PostgreSQL 16+, pgvector, S3-compatible object storage, pytest, Ruff, mypy, TypeScript, Next.js, pnpm, Docker Compose.

## Global Constraints

- Follow `AGENTS.md` without exception.
- V1 business integrations are read-only.
- ACL filtering occurs before retrieval result exposure.
- Agent never receives DB credentials and never executes arbitrary SQL.
- Wiki generated content starts as DRAFT and requires authorized human promotion.
- Unit tests are offline and deterministic.
- Use synthetic shipyard data only.

---

## File structure

```text
apps/api/              HTTP API
apps/web/              Pilot UI
packages/domain/       framework-independent domain
packages/contracts/    typed cross-service contracts
packages/common/       config/logging helpers
services/ingestion/    document pipeline
services/retrieval/    lexical/vector/hybrid retrieval
services/wiki/         governed durable knowledge
services/tool_server/  typed tool registry/runtime
services/agent/        single Agent router/planner/runtime
services/eval/         eval runner/reporting
services/risk/         deterministic risk features
services/model_gateway/model ports
adapters/              infrastructure/vendor adapters
infra/postgres/        DB persistence
tests/                 unit/integration/security/eval/e2e
tasks/                 Codex-executable task specs
```

---
### Task 1: Repository bootstrap

**Dependencies:** None

**Files:**
- Create/Modify: `pyproject.toml`
- Create/Modify: `docker-compose.yml`
- Create/Modify: `apps/api/main.py`
- Create/Modify: `tests/unit/test_health.py`
- Create/Modify: `infra/postgres/README.md`

**Deliverable:** Create the minimal Python monorepo, API health endpoint, PostgreSQL/pgvector Docker service, migration plumbing, and quality commands. No domain or AI features.

**Acceptance:**
- [ ] `docker compose up -d` starts PostgreSQL and API.
- [ ] `GET /health` returns 200 with a typed payload.
- [ ] pytest, Ruff, and mypy commands exist and pass.
- [ ] No LLM/RAG dependencies are introduced.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/001-repository-bootstrap.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 001 changes with a scoped message such as `feat: complete task 001 repository-bootstrap`.

### Task 2: CI and quality gates

**Dependencies:** 001

**Files:**
- Create/Modify: `.github/workflows/ci.yml`
- Create/Modify: `README.md`

**Deliverable:** Add CI that runs unit tests, Ruff, and mypy; add pre-commit/local make-or-task commands with identical checks.

**Acceptance:**
- [ ] CI is deterministic and uses synthetic/local dependencies only.
- [ ] A deliberately failing test would fail CI.
- [ ] Developer commands are documented in README.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/002-ci-quality-gates.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 002 changes with a scoped message such as `feat: complete task 002 ci-quality-gates`.

### Task 3: Configuration and structured logging

**Dependencies:** 001

**Files:**
- Create/Modify: `packages/common/config.py`
- Create/Modify: `packages/common/logging.py`
- Create/Modify: `apps/api/main.py`
- Create/Modify: `tests/unit/test_config.py`

**Deliverable:** Implement typed environment configuration and structured request logging without secrets.

**Acceptance:**
- [ ] Missing required config fails fast with readable error.
- [ ] Health endpoint emits request ID.
- [ ] Sensitive env values are never printed.
- [ ] Unit tests cover redaction.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/003-configuration-logging.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 003 changes with a scoped message such as `feat: complete task 003 configuration-logging`.

### Task 4: Authentication stub and authorization context

**Dependencies:** 003

**Files:**
- Create/Modify: `packages/contracts/auth.py`
- Create/Modify: `services/auth/service.py`
- Create/Modify: `adapters/auth/local.py`
- Create/Modify: `tests/unit/test_authorization_scope.py`

**Deliverable:** Create server-side UserContext and AuthorizationScope primitives with a local development authentication adapter. No external IdP yet.

**Acceptance:**
- [ ] User identity cannot be supplied through model/tool arguments.
- [ ] AuthorizationScope supports role, department, ship/project scope, security level.
- [ ] Default scope is deny-by-default.
- [ ] Tests cover scope intersection.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/004-auth-context.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 004 changes with a scoped message such as `feat: complete task 004 auth-context`.

### Task 5: Core Shipyard domain entities

**Dependencies:** 001,003

**Files:**
- Create/Modify: `packages/domain/entities.py`
- Create/Modify: `packages/domain/value_objects.py`
- Create/Modify: `tests/unit/domain/test_entities.py`

**Deliverable:** Implement framework-independent domain types for Ship, ShipSystem, Drawing, Equipment, Material, BOMItem, Supplier, PurchaseOrder, and ProjectTask.

**Acceptance:**
- [ ] Domain package imports no FastAPI/SQLAlchemy/LLM SDK.
- [ ] External-source fields exist on all sourced records.
- [ ] Domain invariants have unit tests.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/005-domain-core.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 005 changes with a scoped message such as `feat: complete task 005 domain-core`.

### Task 6: Domain persistence and migrations

**Dependencies:** 005

**Files:**
- Create/Modify: `infra/postgres/models.py`
- Create/Modify: `infra/postgres/repositories.py`
- Create/Modify: `alembic/versions/*`
- Create/Modify: `tests/integration/test_domain_repository.py`

**Deliverable:** Add SQLAlchemy persistence models, repositories, and Alembic migrations for V1 domain entities.

**Acceptance:**
- [ ] Canonical internal IDs are separate from source IDs.
- [ ] FK relationships match docs/02-domain-model.md.
- [ ] Repository integration tests run against PostgreSQL.
- [ ] Migration upgrades from empty DB.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/006-domain-persistence.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 006 changes with a scoped message such as `feat: complete task 006 domain-persistence`.

### Task 7: Entity aliases and canonicalization

**Dependencies:** 006

**Files:**
- Create/Modify: `packages/domain/aliases.py`
- Create/Modify: `infra/postgres/alias_repository.py`
- Create/Modify: `services/entity_resolution/service.py`
- Create/Modify: `tests/unit/test_entity_aliases.py`

**Deliverable:** Implement EntityAlias persistence and normalization for supplier/equipment/material aliases without automatic fuzzy merges.

**Acceptance:**
- [ ] Wärtsilä/Wartsila/瓦锡兰 can be explicitly linked to one canonical supplier fixture.
- [ ] No fuzzy candidate is auto-merged.
- [ ] Alias lookup is scope-safe and tested.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/007-entity-aliases.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 007 changes with a scoped message such as `feat: complete task 007 entity-aliases`.

### Task 8: Synthetic shipyard fixture dataset

**Dependencies:** 006,007

**Files:**
- Create/Modify: `tests/fixtures/shipyard/*.json`
- Create/Modify: `tests/fixtures/loader.py`
- Create/Modify: `tests/integration/test_fixture_loader.py`

**Deliverable:** Create deterministic synthetic fixtures for at least two ships, drawings, equipment, BOM, POs, suppliers, and project tasks.

**Acceptance:**
- [ ] No real company/customer data appears.
- [ ] Fixtures include overdue and non-overdue procurement cases.
- [ ] Fixtures include alias cases and two security scopes.
- [ ] Reusable fixture loader exists for integration/eval tests.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/008-synthetic-fixtures.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 008 changes with a scoped message such as `feat: complete task 008 synthetic-fixtures`.

### Task 9: Document/version/chunk schema

**Dependencies:** 006

**Files:**
- Create/Modify: `packages/domain/documents.py`
- Create/Modify: `infra/postgres/document_models.py`
- Create/Modify: `services/ingestion/document_store.py`
- Create/Modify: `tests/integration/test_document_versions.py`

**Deliverable:** Implement Document, DocumentVersion, DocumentChunk metadata and migrations including checksum, source, ACL metadata, and structural location.

**Acceptance:**
- [ ] DocumentVersion is immutable by service contract.
- [ ] Chunk IDs are deterministic.
- [ ] Ship/project/department/security metadata is supported.
- [ ] Integration tests verify version coexistence.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/009-document-schema.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 009 changes with a scoped message such as `feat: complete task 009 document-schema`.

### Task 10: File parser adapters

**Dependencies:** 009

**Files:**
- Create/Modify: `services/ingestion/parser.py`
- Create/Modify: `adapters/parsers/*.py`
- Create/Modify: `tests/unit/ingestion/test_parsers.py`

**Deliverable:** Implement parser interface and local adapters for TXT, Markdown, DOCX, XLSX, and text-layer PDF.

**Acceptance:**
- [ ] All parsers return a common structured representation.
- [ ] Parser errors are typed.
- [ ] No OCR is silently invoked.
- [ ] Synthetic fixtures cover every format.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/010-parser-adapters.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 010 changes with a scoped message such as `feat: complete task 010 parser-adapters`.

### Task 11: Structure-aware chunking

**Dependencies:** 010

**Files:**
- Create/Modify: `services/ingestion/chunker.py`
- Create/Modify: `tests/unit/ingestion/test_chunker.py`

**Deliverable:** Implement deterministic heading/section/table/paragraph chunking with a fallback size-based strategy only when structure is unavailable.

**Acceptance:**
- [ ] Same version produces same chunk IDs.
- [ ] Sections/pages propagate into chunk metadata.
- [ ] Tables are not split row-by-row unless size requires it.
- [ ] Tests cover class-rule-like hierarchy.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/011-structural-chunking.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 011 changes with a scoped message such as `feat: complete task 011 structural-chunking`.

### Task 12: Optional scanned-PDF OCR adapter

**Dependencies:** 010

**Files:**
- Create/Modify: `services/ingestion/ocr.py`
- Create/Modify: `adapters/ocr/fake.py`
- Create/Modify: `tests/unit/ingestion/test_ocr_flow.py`

**Deliverable:** Add an OCR port and an optional local adapter boundary for scanned PDFs. Keep OCR dependency optional and disabled by default.

**Acceptance:**
- [ ] Scanned PDF is detected and returns OCR_REQUIRED when adapter disabled.
- [ ] OCR result preserves page numbers.
- [ ] No OCR engine leaks into domain/service interfaces.
- [ ] Tests use fake OCR adapter.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/012-ocr-adapter.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 012 changes with a scoped message such as `feat: complete task 012 ocr-adapter`.

### Task 13: Lexical retrieval

**Dependencies:** 009,011

**Files:**
- Create/Modify: `packages/contracts/evidence.py`
- Create/Modify: `services/retrieval/lexical.py`
- Create/Modify: `tests/integration/retrieval/test_lexical_acl.py`

**Deliverable:** Implement ACL-filtered lexical search over normalized chunks using a PostgreSQL-backed lexical approach suitable for V1.

**Acceptance:**
- [ ] Authorization filter is applied inside query path before result return.
- [ ] Supports document type/ship/project filters.
- [ ] Returns KnowledgeEvidence contracts.
- [ ] Cross-project test returns zero leaked chunks.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/013-lexical-retrieval.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 013 changes with a scoped message such as `feat: complete task 013 lexical-retrieval`.

### Task 14: Vector retrieval with pgvector

**Dependencies:** 013

**Files:**
- Create/Modify: `services/model_gateway/embedding.py`
- Create/Modify: `adapters/embedding/fake.py`
- Create/Modify: `services/retrieval/vector.py`
- Create/Modify: `alembic/versions/*`
- Create/Modify: `tests/integration/retrieval/test_vector_acl.py`

**Deliverable:** Implement embedding port, fake deterministic embedding adapter, pgvector storage/index, and ACL-filtered vector retrieval.

**Acceptance:**
- [ ] Unit/integration tests never require external model.
- [ ] Embedding dimension is configuration-controlled.
- [ ] ACL is enforced before/with vector query.
- [ ] Evidence contains vector score.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/014-vector-retrieval.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 014 changes with a scoped message such as `feat: complete task 014 vector-retrieval`.

### Task 15: Hybrid retrieval and reranking

**Dependencies:** 013,014

**Files:**
- Create/Modify: `services/retrieval/hybrid.py`
- Create/Modify: `services/model_gateway/reranker.py`
- Create/Modify: `adapters/reranker/fake.py`
- Create/Modify: `tests/unit/retrieval/test_hybrid.py`

**Deliverable:** Merge lexical/vector candidates, deduplicate by chunk, add reranker port with fake adapter, and produce ranked Evidence.

**Acceptance:**
- [ ] Weights/config are explicit and tested.
- [ ] Duplicate chunks collapse deterministically.
- [ ] Reranker failure degrades to hybrid score with warning.
- [ ] Recall-oriented tests use a curated fixture set.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/015-hybrid-rerank.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 015 changes with a scoped message such as `feat: complete task 015 hybrid-rerank`.

### Task 16: Knowledge search API and citations

**Dependencies:** 015,004

**Files:**
- Create/Modify: `apps/api/routes/knowledge.py`
- Create/Modify: `packages/contracts/knowledge.py`
- Create/Modify: `tests/integration/api/test_knowledge_search.py`

**Deliverable:** Expose authenticated knowledge search with filters and evidence; add an answer-independent citation payload for UI/Agent use.

**Acceptance:**
- [ ] Unauthorized filters cannot broaden user scope.
- [ ] Every result has source/version/chunk identity.
- [ ] Page/section shown when available.
- [ ] API integration tests cover 200/403/empty.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/016-knowledge-api.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 016 changes with a scoped message such as `feat: complete task 016 knowledge-api`.

### Task 17: LLM Wiki persistence model

**Dependencies:** 006,009

**Files:**
- Create/Modify: `packages/domain/wiki.py`
- Create/Modify: `infra/postgres/wiki_models.py`
- Create/Modify: `services/wiki/service.py`
- Create/Modify: `tests/integration/wiki/test_wiki_lifecycle.py`

**Deliverable:** Implement WikiPage, WikiRevision, WikiClaim, WikiSource, WikiLink and lifecycle states.

**Acceptance:**
- [ ] Every claim requires provenance.
- [ ] DRAFT/VERIFIED/CANONICAL/DEPRECATED enforced.
- [ ] Revision history is immutable.
- [ ] No Agent code is introduced.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/017-wiki-schema.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 017 changes with a scoped message such as `feat: complete task 017 wiki-schema`.

### Task 18: Wiki review and promotion workflow

**Dependencies:** 017,004

**Files:**
- Create/Modify: `services/wiki/review.py`
- Create/Modify: `services/audit/service.py`
- Create/Modify: `tests/security/test_wiki_promotion.py`

**Deliverable:** Implement authorized human workflow for DRAFT->VERIFIED->CANONICAL->DEPRECATED and audit every transition.

**Acceptance:**
- [ ] Agent/service account without review role cannot promote.
- [ ] Invalid transitions fail.
- [ ] Audit record includes actor/time/from/to.
- [ ] Tests cover deny and success cases.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/018-wiki-review-workflow.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 018 changes with a scoped message such as `feat: complete task 018 wiki-review-workflow`.

### Task 19: Wiki draft compiler

**Dependencies:** 015,017

**Files:**
- Create/Modify: `services/wiki/compiler.py`
- Create/Modify: `services/model_gateway/wiki_compiler.py`
- Create/Modify: `adapters/llm/fake_wiki_compiler.py`
- Create/Modify: `tests/unit/wiki/test_compiler.py`

**Deliverable:** Implement a model-agnostic compilation pipeline that converts Evidence sets into DRAFT page/claim proposals through a fake compiler adapter first.

**Acceptance:**
- [ ] Every factual claim links to >=1 source.
- [ ] Conflicting claims can coexist.
- [ ] Generated pages always DRAFT.
- [ ] Tests reject source-less generated claims.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/019-wiki-compiler.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 019 changes with a scoped message such as `feat: complete task 019 wiki-compiler`.

### Task 20: Wiki search tool service

**Dependencies:** 017,018

**Files:**
- Create/Modify: `services/wiki/search.py`
- Create/Modify: `packages/contracts/wiki.py`
- Create/Modify: `tests/security/test_wiki_search_acl.py`

**Deliverable:** Implement ACL-aware Wiki retrieval returning pages/claims/provenance, respecting lifecycle visibility.

**Acceptance:**
- [ ] Normal users see only permitted VERIFIED/CANONICAL content by default.
- [ ] Reviewers may request DRAFT within scope.
- [ ] Provenance is returned.
- [ ] Security tests cover cross-project Wiki leakage.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/020-wiki-search.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 020 changes with a scoped message such as `feat: complete task 020 wiki-search`.

### Task 21: Typed tool runtime and audit

**Dependencies:** 004,008

**Files:**
- Create/Modify: `packages/contracts/tools.py`
- Create/Modify: `services/tool_server/registry.py`
- Create/Modify: `services/tool_server/runtime.py`
- Create/Modify: `tests/unit/tool_server/test_runtime.py`

**Deliverable:** Implement transport-independent ToolDefinition/ToolCall/ToolResult contracts, registry, server-side UserContext injection, timeout, and audit.

**Acceptance:**
- [ ] Model arguments cannot override UserContext.
- [ ] Unknown tool denied.
- [ ] Timeout is explicit typed failure.
- [ ] Every call writes audit metadata.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/021-tool-runtime.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 021 changes with a scoped message such as `feat: complete task 021 tool-runtime`.

### Task 22: Knowledge and Wiki tools

**Dependencies:** 016,020,021

**Files:**
- Create/Modify: `services/tool_server/tools/knowledge.py`
- Create/Modify: `tests/unit/tool_server/test_knowledge_tools.py`

**Deliverable:** Expose search_knowledge and search_wiki through the typed tool runtime without duplicating retrieval/wiki logic.

**Acceptance:**
- [ ] Tool schemas validate limit/filter types.
- [ ] Authorization scope is forwarded server-side.
- [ ] Tool returns typed evidence.
- [ ] Contract tests cover malformed arguments.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/022-knowledge-tools.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 022 changes with a scoped message such as `feat: complete task 022 knowledge-tools`.

### Task 23: Mock ship/project/procurement/drawing tools

**Dependencies:** 008,021

**Files:**
- Create/Modify: `services/tool_server/tools/business.py`
- Create/Modify: `services/risk/procurement.py`
- Create/Modify: `tests/integration/tool_server/test_business_tools.py`

**Deliverable:** Implement get_ship_status, get_procurement_status, get_drawing_bom, and deterministic get_risk_summary against repositories/fixtures.

**Acceptance:**
- [ ] No direct Agent dependency.
- [ ] Overdue logic is deterministic and date-tested.
- [ ] Risk reasons expose supporting record IDs.
- [ ] Tools respect allowed_ship_ids.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/023-business-mock-tools.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 023 changes with a scoped message such as `feat: complete task 023 business-mock-tools`.

### Task 24: ERP/MES/PLM adapter ports and MCP adapter

**Dependencies:** 021,023

**Files:**
- Create/Modify: `packages/contracts/source_ports.py`
- Create/Modify: `adapters/erp/fixture.py`
- Create/Modify: `adapters/mes/fixture.py`
- Create/Modify: `adapters/plm/fixture.py`
- Create/Modify: `adapters/mcp/server.py`
- Create/Modify: `tests/integration/test_mcp_exposure.py`

**Deliverable:** Define read-only source ports, provide fixture-backed adapters, and add an MCP transport adapter that exposes only the approved tool registry.

**Acceptance:**
- [ ] Business services depend on ports, not vendor schemas.
- [ ] No write method exists in V1 ports.
- [ ] MCP layer only translates transport to typed ToolCall.
- [ ] Tests prove hidden/unregistered tools are not exposed.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/024-source-adapter-ports-mcp.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 024 changes with a scoped message such as `feat: complete task 024 source-adapter-ports-mcp`.

### Task 25: Agent intent router

**Dependencies:** 022,023

**Files:**
- Create/Modify: `services/agent/router.py`
- Create/Modify: `services/model_gateway/router.py`
- Create/Modify: `tests/unit/agent/test_router.py`

**Deliverable:** Implement model-agnostic intent routing contract with deterministic rule/fake adapter for tests.

**Acceptance:**
- [ ] Supports six documented intents.
- [ ] Low-confidence/ambiguous route has safe fallback.
- [ ] Router cannot execute tools.
- [ ] Evaluation fixtures cover representative queries.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/025-agent-router.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 025 changes with a scoped message such as `feat: complete task 025 agent-router`.

### Task 26: Bounded Agent tool execution loop

**Dependencies:** 021,025

**Files:**
- Create/Modify: `services/agent/runtime.py`
- Create/Modify: `services/agent/planner.py`
- Create/Modify: `tests/unit/agent/test_runtime.py`

**Deliverable:** Implement a single-Agent bounded planner/executor that may call only registered tools and stops on max steps/time/error policy.

**Acceptance:**
- [ ] No arbitrary code/SQL/filesystem/network execution.
- [ ] Max tool steps configurable and tested.
- [ ] Tool failures are preserved in trace.
- [ ] UserContext never comes from model output.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/026-agent-tool-loop.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 026 changes with a scoped message such as `feat: complete task 026 agent-tool-loop`.

### Task 27: Grounded answer synthesis and response envelope

**Dependencies:** 026,022,023

**Files:**
- Create/Modify: `packages/contracts/agent.py`
- Create/Modify: `services/agent/synthesis.py`
- Create/Modify: `adapters/llm/fake_synthesizer.py`
- Create/Modify: `tests/unit/agent/test_synthesis.py`

**Deliverable:** Aggregate document/Wiki/business evidence and synthesize a structured AgentResponse using a model adapter; tests use fake synthesizer.

**Acceptance:**
- [ ] Factual answer sections reference evidence IDs.
- [ ] Business freshness surfaced.
- [ ] Inference is labeled.
- [ ] Empty evidence produces an explicit 'not enough evidence' response.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/027-answer-synthesis.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 027 changes with a scoped message such as `feat: complete task 027 answer-synthesis`.

### Task 28: Evaluation dataset and runner

**Dependencies:** 015,23,27

**Files:**
- Create/Modify: `services/eval/schema.py`
- Create/Modify: `services/eval/runner.py`
- Create/Modify: `tests/eval/dataset/*.jsonl`
- Create/Modify: `tests/eval/test_eval_runner.py`

**Deliverable:** Implement JSONL/YAML eval dataset schema, runner, deterministic graders, and report for retrieval/tool/agent/security cases.

**Acceptance:**
- [ ] Runner works offline on synthetic dataset.
- [ ] Reports pass/fail plus metrics by category.
- [ ] At least 30 initial synthetic eval cases are included.
- [ ] CI can run a fast eval subset.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/028-eval-platform.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 028 changes with a scoped message such as `feat: complete task 028 eval-platform`.

### Task 29: Security adversarial suite

**Dependencies:** 016,20,23,27,28

**Files:**
- Create/Modify: `tests/security/test_retrieval_leakage.py`
- Create/Modify: `tests/security/test_prompt_injection.py`
- Create/Modify: `tests/security/test_tool_abuse.py`
- Create/Modify: `tests/security/test_stale_data.py`

**Deliverable:** Add targeted tests for authorization leakage, prompt injection, malformed tools, SQL-like input, stale data, and Wiki source-of-truth violations.

**Acceptance:**
- [ ] Cross-scope retrieval/tool access is denied.
- [ ] Retrieved prompt injection cannot create tool instructions.
- [ ] Stale business data is labeled.
- [ ] Suite contains at least 20 adversarial cases and passes.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/029-security-hardening.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 029 changes with a scoped message such as `feat: complete task 029 security-hardening`.

### Task 30: Pilot UI and end-to-end demo

**Dependencies:** 016,27,29

**Files:**
- Create/Modify: `apps/web/*`
- Create/Modify: `tests/e2e/*`
- Create/Modify: `README.md`

**Deliverable:** Build minimal authenticated Next.js chat/search UI with answer, evidence drawer, tool/freshness indicators, and synthetic end-to-end demo.

**Acceptance:**
- [ ] One UI entry point supports knowledge and Agent questions.
- [ ] Evidence can be inspected without exposing hidden chain-of-thought.
- [ ] Synthetic 1038-like project demo works end-to-end.
- [ ] E2E test covers knowledge query and procurement-risk query.

- [ ] **Step 1: Open the task specification**
  - Read `tasks/030-pilot-ui-e2e.md`, `AGENTS.md`, and referenced docs.
- [ ] **Step 2: Write the failing test**
  - Add the focused test named by the Task's primary behavior before implementation.
- [ ] **Step 3: Verify red state**
  - Run the focused pytest target and confirm it fails for the expected missing behavior.
- [ ] **Step 4: Implement the minimum behavior**
  - Change only files needed by this Task and preserve package boundaries.
- [ ] **Step 5: Verify green state**
  - Run the focused test, then the relevant unit/integration suite.
- [ ] **Step 6: Quality gate**
  - Run `ruff check .` and `mypy .`; fix all new failures.
- [ ] **Step 7: Independent review gate**
  - Review the diff from a separate Reviewer thread; resolve all P0/P1/P2 findings.
- [ ] **Step 8: Commit**
  - Commit only Task 030 changes with a scoped message such as `feat: complete task 030 pilot-ui-e2e`.
