# ACL-Filtered Lexical Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, mixed Chinese/English PostgreSQL lexical retrieval that returns immutable evidence and enforces document ACLs and metadata filters inside the candidate query.

**Architecture:** Shared contracts define document types, filters, evidence, and a service-owned lexical-search port. A PostgreSQL infrastructure adapter implements one parameterized ACL-filtered FTS/trigram query over immutable documents, versions, and chunks; a schema migration adds explicit document-type metadata and required indexes.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, `pg_trgm`, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-20-lexical-retrieval-design.md`

## Global Constraints

- Original documents and immutable versions remain authoritative; retrieved text is untrusted evidence, never an instruction or live business state.
- `AuthorizationScope` is a server-derived parameter separate from caller/model filters.
- Security-level, department, ship, and project ACL predicates must be inside the PostgreSQL candidate query before ranking, ordering, and `LIMIT`.
- A null ACL dimension is global; a non-null dimension requires exact membership; all present dimensions must pass.
- `DocumentType` is exactly `pdf`, `docx`, `xlsx`, `txt`, or `markdown` and is required immutable `DocumentVersion` metadata.
- `services.retrieval` must not import SQLAlchemy, PostgreSQL infrastructure, parsers, FastAPI, models, Wiki, Agent, or business-source adapters.
- Queries are parameterized, literal wildcard characters are escaped, sessions are read-only, statement timeout is 2,000 ms, and result limit is 1 through 20.
- Lexical score is exactly `0.7 * ts_rank_cd(..., 32) + 0.3 * similarity(...)`; ordering is score descending, source update descending, chunk UUID ascending.
- Tests use synthetic data and only the protected `shipyard_ai_test` database; no model, external search, customer data, or production credential.
- No Task 014 vector/embedding, Task 015 hybrid/reranker, API, Wiki, Agent, tool-runtime, parser, chunker, or OCR behavior may be added.
- Every behavior change follows RED → expected failure → minimal GREEN → relevant suite → Ruff → mypy.

---

### Task 1: Add explicit document-type metadata and lexical indexes

**Files:**
- Create: `packages/common/document_types.py`
- Modify: `packages/common/__init__.py`
- Modify: `packages/domain/documents.py`
- Modify: `services/ingestion/document_store.py`
- Modify: `infra/postgres/document_models.py`
- Modify: `infra/postgres/document_repository.py`
- Create: `infra/postgres/migrations/versions/20260820_0004_add_lexical_retrieval.py`
- Modify: `tests/unit/domain/test_documents.py`
- Modify: `tests/unit/ingestion/test_document_store.py`
- Modify: `tests/integration/test_document_versions.py`

**Interfaces:**
- Produces: `DocumentType` and required `DocumentVersion.document_type` for Tasks 2–4.
- Produces: `document_versions.document_type` plus B-tree, FTS GIN, and trigram GIN indexes for Task 3.

- [ ] **Step 1: Write the `DocumentType` and immutable-version RED tests**

Add the future import and literal domain cases to `tests/unit/domain/test_documents.py`:

```python
from packages.common import DocumentType


def test_document_type_has_the_exact_v1_values() -> None:
    assert [(item.name, item.value) for item in DocumentType] == [
        ("PDF", "pdf"),
        ("DOCX", "docx"),
        ("XLSX", "xlsx"),
        ("TXT", "txt"),
        ("MARKDOWN", "markdown"),
    ]


def test_document_version_requires_an_exact_document_type() -> None:
    version = _version(document_type=DocumentType.PDF)
    assert version.document_type is DocumentType.PDF
    with pytest.raises(
        DocumentValidationError,
        match="^document_type must be a DocumentType$",
    ):
        _version(document_type="pdf")
```

Add `"document_type": DocumentType.PDF` to `_version()` only after capturing
the RED import. Add a store test showing that an identical checksum with
`DOCX` instead of `PDF` raises the existing fixed
`DocumentVersionConflictError`.

- [ ] **Step 2: Run the domain nodes and confirm RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/domain/test_documents.py::test_document_type_has_the_exact_v1_values \
  tests/unit/domain/test_documents.py::test_document_version_requires_an_exact_document_type -v
```

Expected: collection fails because `DocumentType` is absent.

- [ ] **Step 3: Implement the minimum shared enum and domain field**

Create `packages/common/document_types.py`:

```python
"""Approved immutable source-document formats."""

from enum import StrEnum

__all__ = ["DocumentType"]


class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    TXT = "txt"
    MARKDOWN = "markdown"
```

Export it from `packages.common`. Add required field
`document_type: DocumentType` after `source_uri` in `DocumentVersion`, validate
it with `isinstance(value, DocumentType)`, and use the exact error
`document_type must be a DocumentType`. Add it to
`DocumentStore._version_payload()` so a checksum retry cannot change type.

- [ ] **Step 4: Confirm domain/store GREEN and update constructors**

Run Step 2 again, then add `DocumentType.PDF` to every existing
`DocumentVersion` fixture in the three test files and to the PostgreSQL
repository mapping. Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py -v
```

Expected: all pass.

- [ ] **Step 5: Write schema/metadata RED tests**

Extend `test_document_metadata_declares_version_and_chunk_constraints` so the
version columns include `document_type`, version constraints include
`ck_document_versions_document_type`, and indexes include
`ix_document_versions_document_type`. Assert chunk indexes include:

```python
{
    "ix_document_chunks_lexical_tsv",
    "ix_document_chunks_normalized_text_trgm",
} <= {index.name for index in Base.metadata.tables["document_chunks"].indexes}
```

Change the migration-head assertion to `20260820_0004`. Add database
constraint cases for invalid type `"pdfx"` and null type.

Before migration implementation, also add protected Alembic tests that upgrade
to `20260819_0003`, insert synthetic version rows with `.PDF?download=1`,
`.md#section`, and `.xlsx` URIs, upgrade to head, and expect `pdf`, `markdown`,
and `xlsx`. A separate test inserts `synthetic://opaque-object` and expects the
fixed migration failure with no false type installed. Both always downgrade to
base in `finally`. Run:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_document_versions.py \
  -k "metadata_declares or migration_is_current_head or document_type" -v
```

Expected: failures for absent column, constraint, indexes, revision, and
missing backfill/fail-safe migration behavior.

- [ ] **Step 6: Implement model and migration metadata**

Add `document_type: Mapped[str] = mapped_column(Text, nullable=False,
index=True)` and this check to `DocumentVersionModel`:

```python
CheckConstraint(
    "document_type IN ('pdf', 'docx', 'xlsx', 'txt', 'markdown')",
    name="ck_document_versions_document_type",
),
```

Add these indexes to `DocumentChunkModel.__table_args__`:

```python
Index(
    "ix_document_chunks_lexical_tsv",
    text("to_tsvector('simple'::regconfig, normalized_text)"),
    postgresql_using="gin",
),
Index(
    "ix_document_chunks_normalized_text_trgm",
    "normalized_text",
    postgresql_using="gin",
    postgresql_ops={"normalized_text": "gin_trgm_ops"},
),
```

Map `DocumentType` to/from `.value` in the repository, translating invalid
stored values through the existing safe repository error.

Create revision `20260820_0004`, down revision `20260819_0003`. Upgrade in
this exact order: `CREATE EXTENSION IF NOT EXISTS pg_trgm`; add nullable text
column; backfill by stripping URI query/fragment and matching `.pdf`, `.docx`,
`.xlsx`, `.txt`, `.md`, or `.markdown`; raise the fixed migration exception
`cannot infer document_type for existing document version` when any value is
still null; make the column non-null; add the exact-value constraint; add the
three indexes. Downgrade drops Task 013 indexes, constraint, and column but
leaves the potentially shared extension installed.

The backfill SQL must use this literal CASE:

```sql
CASE
  WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\.pdf$' THEN 'pdf'
  WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\.docx$' THEN 'docx'
  WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\.xlsx$' THEN 'xlsx'
  WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\.txt$' THEN 'txt'
  WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\.(md|markdown)$'
    THEN 'markdown'
  ELSE NULL
END
```

- [ ] **Step 7: Confirm migration backfill and unsafe-legacy GREEN**

Run the exact backfill and unmappable-legacy nodes written in Step 5. Expected:
known suffixes persist `pdf`, `markdown`, and `xlsx`; the opaque URI raises the
fixed migration failure and stores no invented type.

- [ ] **Step 8: Verify and commit Task 1**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_document_versions.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  packages/common packages/domain/documents.py services/ingestion/document_store.py \
  infra/postgres/document_models.py infra/postgres/document_repository.py \
  infra/postgres/migrations/versions/20260820_0004_add_lexical_retrieval.py \
  tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py \
  tests/integration/test_document_versions.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  packages/common packages/domain/documents.py services/ingestion/document_store.py \
  infra/postgres/document_models.py infra/postgres/document_repository.py \
  tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py \
  tests/integration/test_document_versions.py
```

Commit:

```bash
git add packages/common packages/domain/documents.py \
  services/ingestion/document_store.py infra/postgres/document_models.py \
  infra/postgres/document_repository.py \
  infra/postgres/migrations/versions/20260820_0004_add_lexical_retrieval.py \
  tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py \
  tests/integration/test_document_versions.py
git commit -m "feat: add document lexical metadata"
```

---

### Task 2: Define immutable evidence contracts and the retrieval service port

**Files:**
- Create: `packages/contracts/evidence.py`
- Modify: `packages/contracts/__init__.py`
- Create: `services/retrieval/__init__.py`
- Create: `services/retrieval/lexical.py`
- Create: `tests/unit/retrieval/__init__.py`
- Create: `tests/unit/retrieval/test_lexical_contracts.py`

**Interfaces:**
- Consumes: Task 1 `DocumentType` and existing `AuthorizationScope`.
- Produces: `KnowledgeFilters`, `KnowledgeEvidence`, `LexicalSearchPort`, `LexicalRetriever`, `RetrievalValidationError`, and `LexicalRetrievalError`.

- [ ] **Step 1: Write the public-contract import RED**

Create `tests/unit/retrieval/test_lexical_contracts.py` with future public
imports, the frozen evidence example below, and literal validation tables for
blank/NUL required text, blank/NUL optional section, page `0`, `-1`, `True`,
and `1.0`, score `-0.1`, `nan`, `inf`, and `-inf` for every score field,
forbidden extra fields, every exact `DocumentType`, UUID filters, and both
contracts' immutability:

```python
def test_knowledge_evidence_is_frozen_and_preserves_provenance() -> None:
    evidence = KnowledgeEvidence(
        document_id=UUID("a1000000-0000-0000-0000-000000000001"),
        version_id=UUID("a1000000-0000-0000-0000-000000000002"),
        chunk_id=UUID("a1000000-0000-0000-0000-000000000003"),
        title="Synthetic welding rule",
        section="4.2",
        page=7,
        source_uri="s3://synthetic/rule.pdf",
        excerpt="Synthetic welding clearance requirement.",
        retrieval_score=0.75,
        lexical_score=0.75,
    )
    assert evidence.lexical_score == 0.75
    assert evidence.vector_score is None
    with pytest.raises(ValidationError):
        evidence.title = "changed"  # type: ignore[misc]
```

Run the node. Expected: collection failure because the evidence module and
exports do not exist.

- [ ] **Step 2: Implement the minimum frozen contracts**

In `packages/contracts/evidence.py`, define a private Pydantic base with
`ConfigDict(extra="forbid", frozen=True)`. Define:

```python
class KnowledgeFilters(_FrozenContract):
    document_type: DocumentType | None = None
    ship_id: UUID | None = None
    project_id: UUID | None = None


class KnowledgeEvidence(_FrozenContract):
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    section: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ] | None = None
    page: Annotated[StrictInt, Field(gt=0)] | None = None
    source_uri: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]
    excerpt: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    retrieval_score: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    lexical_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    vector_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    rerank_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
```

Use one `field_validator` over title, section, source URI, and excerpt to
reject NUL with `text fields must not contain NUL`. Export `DocumentType`,
`KnowledgeFilters`, and `KnowledgeEvidence` from `packages.contracts` without
removing existing auth exports.

- [ ] **Step 3: Confirm exact contract validation GREEN**

Run the whole contract file written in Step 1. Expected: every literal valid
case passes and every invalid case raises the exact Pydantic validation error.

- [ ] **Step 4: Write the service delegation RED**

Add a deterministic recording port, the primary node below, and parameterized
invalid service cases for non-exact query strings, empty/NUL/over-limit query,
non-exact scope/filter objects, boolean/non-integer limit, and limits outside
1–20. Each invalid case expects only `invalid lexical retrieval request` and
proves the port was not called:

```python
def test_lexical_retriever_validates_and_delegates_trusted_scope() -> None:
    scope = AuthorizationScope(
        departments={"engineering"},
        allowed_ship_ids={"a1000000-0000-0000-0000-000000000010"},
        allowed_project_ids={"a1000000-0000-0000-0000-000000000011"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )
    filters = KnowledgeFilters(document_type=DocumentType.PDF)
    port = RecordingLexicalPort([_evidence()])

    result = LexicalRetriever(port).retrieve(
        "  welding clearance  ", scope, filters, limit=7
    )

    assert result == [_evidence()]
    assert port.calls == [("welding clearance", scope, filters, 7)]
```

Run the node. Expected: import failure for absent retrieval service.

- [ ] **Step 5: Implement the minimum service port and validation**

Create `services/retrieval/lexical.py` with:

```python
MAX_QUERY_CHARS = 1000
MAX_RETRIEVAL_RESULTS = 20
_INVALID_REQUEST = "invalid lexical retrieval request"


class RetrievalValidationError(ValueError):
    pass


class LexicalRetrievalError(RuntimeError):
    pass


class LexicalSearchPort(Protocol):
    def search(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]: ...
```

`LexicalRetriever.retrieve()` rejects non-exact strings, stripped empty
queries, NUL, more than 1,000 code points, non-exact scope/filter objects,
boolean/non-integer limits, and values outside 1–20 using only
`invalid lexical retrieval request`. It strips leading/trailing whitespace,
calls the port once, and returns the result list unchanged. Export the five
service names from `services.retrieval`.

- [ ] **Step 6: Confirm service boundary and architecture guards**

Run the delegation and invalid cases written in Step 4. Assert the fixed error
does not contain query or scope values. Add an AST guard proving the service imports
only `__future__`, `typing`, and exact `packages.contracts` targets. Include
malicious snippets `from .. import infra as db` and
`from infra import postgres as db` so relative/alias syntax cannot bypass it.

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/retrieval/test_lexical_contracts.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  packages/contracts services/retrieval tests/unit/retrieval
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  packages/contracts services/retrieval tests/unit/retrieval
```

Expected: all pass with pristine output.

- [ ] **Step 7: Commit Task 2**

```bash
git add packages/contracts services/retrieval tests/unit/retrieval
git commit -m "feat: define lexical retrieval contracts"
```

---

### Task 3: Implement the PostgreSQL lexical adapter and primary retrieval flow

**Files:**
- Create: `infra/postgres/lexical_retrieval.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `tests/unit/retrieval/test_lexical_contracts.py`
- Create: `tests/integration/retrieval/__init__.py`
- Create: `tests/integration/retrieval/test_lexical_acl.py`

**Interfaces:**
- Consumes: Task 1 indexed schema and Task 2 retrieval contracts.
- Produces: `PostgresLexicalSearchAdapter(engine: Engine)` implementing `LexicalSearchPort`.

- [ ] **Step 1: Write the primary cross-project RED integration test**

Create a synthetic helper that inserts two documents, versions, and chunks in
different projects. Both chunks contain `ballast pump maintenance`; only one
project UUID is authorized. Before production implementation, also add literal
cases for English terms, identifier `P-101-A`, Chinese `压载泵`, literal `%`,
`_`, and backslash, PDF/DOCX filter, authorized and unauthorized ship/project
filters, `limit=1`, deterministic tie ordering, exact evidence fields, and a
4,000-code-point excerpt. Add the SQL-path/read-only capture guard in the same
RED test file. The primary node is:

```python
def test_lexical_search_returns_only_the_authorized_project(
    migrated_engine: Engine,
) -> None:
    allowed_project = UUID("a2000000-0000-0000-0000-000000000001")
    denied_project = UUID("a2000000-0000-0000-0000-000000000002")
    allowed_chunk, denied_chunk = _persist_two_project_fixture(
        migrated_engine, allowed_project, denied_project
    )
    scope = AuthorizationScope(
        allowed_project_ids={str(allowed_project)},
        security_level=SecurityLevel.INTERNAL,
    )

    result = LexicalRetriever(
        PostgresLexicalSearchAdapter(migrated_engine)
    ).retrieve("ballast pump", scope, KnowledgeFilters())

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}
    assert all(type(item) is KnowledgeEvidence for item in result)
```

Use `PostgresDocumentRepository` for writes and commit only the synthetic test
fixture. Run the node with `TEST_DATABASE_URL`. Expected: collection failure
because the adapter is absent.

- [ ] **Step 2: Implement literal helpers and statement construction**

Create `infra/postgres/lexical_retrieval.py` with:

```python
LEXICAL_FTS_WEIGHT = 0.7
LEXICAL_TRIGRAM_WEIGHT = 0.3
LEXICAL_STATEMENT_TIMEOUT_MS = 2000
MAX_EVIDENCE_EXCERPT_CHARS = 2000
_UNAVAILABLE = "lexical retrieval unavailable"
_SIMPLE_CONFIG = literal_column("'simple'::regconfig")
```

Add `_canonical_scope_uuids()` that keeps an identifier only when UUID parsing
succeeds and `str(parsed) == value.lower()`. Add `_literal_ilike_pattern()`
that escapes backslash, `%`, and `_` before wrapping the query in `%...%`.
Add `_excerpt()` that returns at most 2,000 code points centered on the first
case-insensitive literal occurrence or starts at zero when absent.

Build one SELECT joining chunk, version, and document. Use:

```python
plain_query = func.plainto_tsquery(_SIMPLE_CONFIG, bindparam("query"))
vector = func.to_tsvector(
    _SIMPLE_CONFIG, DocumentChunkModel.normalized_text
)
fts_score = func.ts_rank_cd(vector, plain_query, 32)
trigram_score = func.similarity(
    DocumentChunkModel.normalized_text, bindparam("query")
)
lexical_score = (
    LEXICAL_FTS_WEIGHT * fts_score
    + LEXICAL_TRIGRAM_WEIGHT * trigram_score
).label("lexical_score")
```

The WHERE list contains the FTS-or-literal match, clearance, and all three
null-or-membership ACL predicates. Append exact document-type/ship/project
filters only when present. Order by score descending, version
`source_updated_at` descending, then chunk UUID ascending, and bind the limit
in the same statement.

- [ ] **Step 3: Implement read-only execution and evidence assembly**

`PostgresLexicalSearchAdapter` stores an `Engine`, not a caller-owned Session.
Its `search()` performs:

```python
with Session(self._engine) as session, session.begin():
    session.execute(text("SET TRANSACTION READ ONLY"))
    session.scalar(
        select(
            func.set_config(
                "statement_timeout",
                str(LEXICAL_STATEMENT_TIMEOUT_MS),
                True,
            )
        )
    )
    rows = session.execute(statement, parameters).all()
```

Convert only authorized rows to `KnowledgeEvidence`. Set
`retrieval_score == lexical_score == max(0.0, float(row.lexical_score))` and
leave vector/rerank scores unset. Catch only `SQLAlchemyError` and raise
`LexicalRetrievalError("lexical retrieval unavailable") from None`. Export
the adapter from `infra.postgres` without removing existing exports.

- [ ] **Step 4: Confirm the primary GREEN**

Run the primary node again. Expected: one authorized evidence result and no
denied chunk.

- [ ] **Step 5: Confirm ranking, filter, and contract GREEN**

Run the literal integration cases written in Step 1 for:

- English terms, identifier `P-101-A`, and Chinese `压载泵`;
- literal `%`, `_`, and backslash query characters match only stored literals;
- PDF versus DOCX filter;
- authorized ship and project filters;
- out-of-scope ship/project filters return `[]`;
- `limit=1` returns the highest-ranked row;
- equal-score rows use newer source time, then ascending chunk UUID;
- exact evidence title/version/page/section/URI/excerpt/score fields; and
- a 4,000-code-point chunk returns a 2,000-code-point excerpt containing the
  literal query.

Expected scores do not reuse the production expression. Assert result order,
finite non-negative values, and equality of lexical/retrieval scores.

- [ ] **Step 6: Confirm SQL-path and add architecture import guards**

Run the SQLAlchemy `before_cursor_execute` guard written in Step 1. Capture
the candidate SELECT and assert its normalized SQL references
`security_level`, `department`, `ship_id`, `project_id`, and `LIMIT`; returned
rows remain the behavior oracle. Capture setup statements and prove the adapter
issues `SET TRANSACTION READ ONLY` and transaction-local timeout `2000`.

Add an AST guard proving the infrastructure module imports only standard
library, SQLAlchemy, exact PostgreSQL models, packages contracts, and the
service error/port surface. Forbid parser, model SDK, API, Wiki, Agent,
business adapter, vector, embedding, hybrid, and reranker targets.

- [ ] **Step 7: Verify and commit Task 3**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/retrieval/test_lexical_acl.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/retrieval/test_lexical_contracts.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  infra/postgres/lexical_retrieval.py infra/postgres/__init__.py \
  tests/integration/retrieval tests/unit/retrieval
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  infra/postgres/lexical_retrieval.py infra/postgres/__init__.py \
  tests/integration/retrieval tests/unit/retrieval
```

Commit:

```bash
git add infra/postgres/lexical_retrieval.py infra/postgres/__init__.py \
  tests/integration/retrieval tests/unit/retrieval
git commit -m "feat: search document chunks lexically"
```

---

### Task 4: Harden every ACL dimension, document the boundary, and complete Task 013

**Files:**
- Modify: `tests/integration/retrieval/test_lexical_acl.py`
- Modify: `tests/unit/retrieval/test_lexical_contracts.py`
- Modify if a RED test proves necessary: `infra/postgres/lexical_retrieval.py`
- Modify if a RED test proves necessary: `services/retrieval/lexical.py`
- Modify: `docs/03-knowledge-system.md`
- Modify: `docs/06-security.md`

**Interfaces:**
- Consumes: completed Task 013 contracts and PostgreSQL adapter.
- Produces: security-complete lexical retrieval ready for Task 014 without widening ACLs.

- [ ] **Step 1: Add complete security characterization matrices**

Add parameterized synthetic versions so one matching chunk is denied by each
single dimension:

```text
security: CONFIDENTIAL document / INTERNAL scope
department: quality document / engineering scope
ship: ship B document / only ship A allowed
project: project B document / only project A allowed
```

Add intersection cases where the same version has department, ship, and
project metadata and exactly one dimension differs. Every denied case returns
`[]`. Add a public, fully global document and prove an empty default scope can
retrieve it but cannot retrieve any scoped document.

Run these new nodes before modifying production. Expected: they pass if Task 3
fully implemented the approved ACL predicates. Any failure is a genuine RED
for a missing security behavior and must be fixed minimally before proceeding;
do not weaken or mutate correct production merely to manufacture a RED state.

- [ ] **Step 2: Add malformed-scope and no-bypass coverage**

Use scope ID sets containing canonical allowed UUIDs mixed with these invalid
values:

```python
["not-a-uuid", "{a2000000-0000-0000-0000-000000000001}", "1"]
```

The auth-contract test separately proves a blank member is rejected before
retrieval. Retrieval tests prove the other three values neither raise nor
grant a denied ship/project. Uppercase canonical UUID text is accepted after
lowercasing; brace-wrapped UUID is denied. Add out-of-scope ship and project
filters and assert zero rows without a second unfiltered candidate SELECT.

- [ ] **Step 3: Add safe failure and transaction behavior tests**

Point a temporary Engine at a guaranteed unavailable local port and assert:

```python
with pytest.raises(
    LexicalRetrievalError,
    match="^lexical retrieval unavailable$",
) as captured:
    adapter.search("secret query text", scope, filters, 10)
assert "secret query text" not in str(captured.value)
assert captured.value.__cause__ is None
assert captured.value.__context__ is None or captured.value.__suppress_context__
```

Use the SQL event guard to prove retrieval emits no `INSERT`, `UPDATE`,
`DELETE`, or DDL. Verify successful search returns the Engine pool to zero
checked-out connections and does not alter document/version/chunk row counts.

- [ ] **Step 4: Apply only test-proven minimal hardening**

If a RED test exposes a missing predicate, unsafe UUID conversion, leaked
database error, wildcard issue, or transaction side effect, make the smallest
production change and rerun the exact failing node before the full focused
suite. Do not add a vector/hybrid abstraction.

- [ ] **Step 5: Document the implemented boundary**

Update `docs/03-knowledge-system.md` retrieval section with the exact public
contracts, explicit `DocumentType`, FTS/trigram score, all ACL semantics,
deterministic ordering, all-version behavior, evidence/excerpt behavior, and
Task 014/015 exclusions.

Update `docs/06-security.md` to state that lexical candidates are filtered in
the PostgreSQL query before ranking/limit; null means global for that
dimension; all non-null dimensions intersect; queries are parameterized and
read-only with a 2,000 ms timeout and 20-row maximum; retrieved text remains
untrusted.

- [ ] **Step 6: Run focused, adjacent, migration, and security suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/retrieval tests/unit/domain/test_documents.py \
  tests/unit/ingestion/test_document_store.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/retrieval tests/integration/test_document_versions.py \
  tests/security -v
```

Expected: zero failures and zero skips in explicitly database-configured paths.

- [ ] **Step 7: Run complete gate and scope audit**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
git diff --check 0b667bb...HEAD
git diff --name-only 0b667bb...HEAD
```

Expected: all tests, Ruff, mypy, and pip pass; one Alembic head is
`20260820_0004`; only the approved Task 013 spec/plan, document metadata and
migration, evidence/retrieval contracts, PostgreSQL adapter, tests, and two
docs appear. No dependency lock, vector/embedding, hybrid/reranker, API, Wiki,
Agent, tool-runtime, parser, chunker, or OCR file may appear.

- [ ] **Step 8: Record acceptance evidence and commit Task 4**

The report maps exact tests to:

1. ACL predicates inside candidate SQL before `LIMIT`;
2. document-type, ship, and project filters;
3. exact `KnowledgeEvidence` output;
4. cross-project zero leakage;
5. department/ship/project/security and global-null behavior;
6. Chinese/English/identifier/literal-wildcard retrieval;
7. read-only, timeout, row-limit, fixed-error, and source-of-truth behavior;
8. no real data/secrets and no Task 014 work.

Commit only files that actually changed after RED:

```bash
git add tests/integration/retrieval/test_lexical_acl.py \
  tests/unit/retrieval/test_lexical_contracts.py \
  infra/postgres/lexical_retrieval.py services/retrieval/lexical.py \
  docs/03-knowledge-system.md docs/06-security.md
git commit -m "test: harden lexical retrieval authorization"
```

- [ ] **Step 9: Request final independent review and stop before Task 014**

Request a read-only spec/code/security review across `0b667bb...HEAD` against
`AGENTS.md`, `tasks/013-lexical-retrieval.md`, the approved design, and this
plan. Resolve every verified P0/P1/P2 with focused TDD and rerun the complete
gate after material fixes. Report P3 findings as known limitations. Do not
merge, push, or begin Task 014 without explicit user choice.
