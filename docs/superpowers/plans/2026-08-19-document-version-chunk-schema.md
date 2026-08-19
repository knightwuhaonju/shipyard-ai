# Document, Version, and Chunk Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement immutable document/version/chunk domain contracts, an ingestion service port, deterministic Chunk IDs, PostgreSQL persistence, and migration `20260819_0003` for Task 009.

**Architecture:** Domain and service contracts remain framework-independent; the ingestion service depends on a repository Protocol, and PostgreSQL implements that port through separate SQLAlchemy models and a caller-transaction-owned adapter. ACL metadata is stored once on immutable DocumentVersion rows, while deterministic DocumentChunk rows inherit authorization through their version foreign key.

**Tech Stack:** Python 3.12, frozen dataclasses, UUIDv5, Pydantic-compatible shared `IntEnum`, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-19-document-version-chunk-schema-design.md`

## Global Constraints

- Implement Task 009 only; do not create parser, chunker, OCR, retrieval, embedding, API, or Task 010 code.
- Domain types must not import Pydantic, SQLAlchemy, PostgreSQL, FastAPI, object-store SDKs, or model SDKs.
- Preserve existing `SecurityLevel` imports from `packages.contracts` and `packages.contracts.auth` while moving the enum implementation to `packages.common.security`.
- `DocumentVersion` must carry `document_id`, `version_id`, a 64-character lowercase SHA-256 checksum, `source_uri`, timezone-aware `source_updated_at`, `security_level`, and optional `ship_id`, `project_id`, and `department`.
- `DocumentChunk` IDs are UUIDv5 values derived from fixed namespace plus canonical JSON of `version_id`, `structural_path`, and `ordinal`.
- ACL metadata lives on immutable versions, not duplicated on chunks.
- Service and repository APIs are insert/read-only; no update, delete, upsert, commit, generated SQL, or production source access.
- PostgreSQL revision is exactly `20260819_0003` with sole parent `20260818_0002`.
- Tests use deterministic synthetic values and only the guarded database `postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test`.
- Repository/service errors must not interpolate source IDs, checksums, URIs, departments, normalized text, database URLs, or environment values.
- Every behavior slice follows RED, minimal GREEN, relevant suite, Ruff, and mypy before commit.

## File Map

- `packages/common/security.py`: shared framework-independent ordered security enum.
- `packages/domain/documents.py`: immutable document/version/chunk types and deterministic Chunk ID function.
- `services/ingestion/document_store.py`: repository port, value-safe service errors, and immutable registration/read service.
- `infra/postgres/document_models.py`: three SQLAlchemy tables using the existing `Base`.
- `infra/postgres/document_repository.py`: PostgreSQL implementation of the service port.
- `infra/postgres/migrations/versions/20260819_0003_create_documents.py`: linear migration from alias schema head.
- `tests/unit/domain/test_documents.py`: domain validation, exports, immutability, and ID determinism.
- `tests/unit/ingestion/test_document_store.py`: service behavior with a deterministic in-memory fake.
- `tests/integration/test_document_versions.py`: metadata, migration, repository, transaction, ACL, coexistence, and recovery coverage.
- Existing package exports, migration environment, current-head assertions, and documentation change only where listed by the approved spec.

---

### Task 1: Shared SecurityLevel and Immutable Document Domain

**Files:**
- Create: `packages/common/security.py`
- Create: `packages/domain/documents.py`
- Create: `tests/unit/domain/test_documents.py`
- Modify: `packages/common/__init__.py`
- Modify: `packages/contracts/auth.py`
- Modify: `packages/domain/__init__.py`
- Test: `tests/unit/test_authorization_scope.py`

**Interfaces:**
- Consumes: existing `packages.contracts.auth.SecurityLevel` values and domain frozen-dataclass conventions.
- Produces: `SecurityLevel`, `DocumentValidationError`, `Document`, `DocumentVersion`, `DocumentChunk`, and `document_chunk_id(version_id, structural_path, ordinal) -> UUID`.

- [ ] **Step 1: Write failing shared-enum and domain tests**

Create `tests/unit/domain/test_documents.py` with fixed values:

```python
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.common import SecurityLevel as CommonSecurityLevel
from packages.contracts import SecurityLevel as ContractSecurityLevel
from packages.domain import (
    Document,
    DocumentChunk,
    DocumentValidationError,
    DocumentVersion,
    document_chunk_id,
)

DOCUMENT_ID = UUID("90000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("90000000-0000-0000-0000-000000000002")
UPDATED_AT = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


def _version(**changes: object) -> DocumentVersion:
    values: dict[str, object] = {
        "version_id": VERSION_ID,
        "document_id": DOCUMENT_ID,
        "checksum": "a" * 64,
        "source_uri": "s3://synthetic-documents/rule-a.pdf",
        "source_updated_at": UPDATED_AT,
        "security_level": CommonSecurityLevel.INTERNAL,
        "ship_id": UUID("90000000-0000-0000-0000-000000000003"),
        "project_id": UUID("90000000-0000-0000-0000-000000000004"),
        "department": "Synthetic Engineering",
    }
    values.update(changes)
    return DocumentVersion(**values)  # type: ignore[arg-type]


def test_security_level_is_one_shared_framework_independent_type() -> None:
    assert CommonSecurityLevel is ContractSecurityLevel
    assert [level.value for level in CommonSecurityLevel] == [0, 1, 2, 3]


def test_document_version_is_immutable_and_preserves_acl_metadata() -> None:
    version = _version()
    assert version.ship_id == UUID("90000000-0000-0000-0000-000000000003")
    assert version.project_id == UUID("90000000-0000-0000-0000-000000000004")
    assert version.department == "Synthetic Engineering"
    with pytest.raises(FrozenInstanceError):
        version.checksum = "b" * 64  # type: ignore[misc]


def test_document_chunk_id_is_stable_and_path_boundary_safe() -> None:
    first = document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 0)
    assert first == document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 0)
    assert first != document_chunk_id(VERSION_ID, ("Chapter 1", "a", "b"), 0)
    assert first != document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 1)
    chunk = DocumentChunk(
        chunk_id=first,
        version_id=VERSION_ID,
        structural_path=("Chapter 1", "a/b"),
        ordinal=0,
        normalized_text="Synthetic class-rule paragraph.",
        page=1,
        section="Chapter 1",
    )
    assert chunk.chunk_id == first
```

Add parameterized invalid cases for:

```python
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"checksum": "A" * 64}, "checksum must be lowercase SHA-256 text"),
        ({"checksum": "a" * 63}, "checksum must be lowercase SHA-256 text"),
        ({"source_uri": "  "}, "source_uri must be non-blank"),
        ({"source_updated_at": datetime(2026, 8, 19, 8, 0)}, "source_updated_at must be timezone-aware"),
        ({"security_level": 1}, "security_level must be a SecurityLevel"),
        ({"department": " "}, "department must be non-blank when provided"),
    ],
)
def test_document_version_rejects_invalid_metadata(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(DocumentValidationError, match=f"^{message}$"):
        _version(**changes)
```

Add exact tests that reject a list instead of tuple for `structural_path`, blank path elements, negative/bool ordinals, zero/bool pages, blank normalized text/section, and a random caller-supplied Chunk UUID.

- [ ] **Step 2: Run tests to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_documents.py -v
```

Expected: collection ERROR because the new common/domain exports do not exist.

- [ ] **Step 3: Implement the shared enum and domain contracts**

Create `packages/common/security.py`:

```python
"""Shared framework-independent information-security levels."""

from enum import IntEnum


class SecurityLevel(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
```

Move only the enum definition out of `packages/contracts/auth.py`; import it there with `from packages.common.security import SecurityLevel`. Export the same object from `packages.common.__init__`.

In `packages/domain/documents.py`, use this exact deterministic-ID shape:

```python
_CHUNK_ID_NAMESPACE = UUID("90f13714-cfb7-5871-a2ef-92c413d6e55e")
_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def document_chunk_id(
    version_id: UUID,
    structural_path: tuple[str, ...],
    ordinal: int,
) -> UUID:
    _require_uuid("version_id", version_id)
    _require_structural_path(structural_path)
    _require_non_negative_integer("ordinal", ordinal)
    payload = json.dumps(
        {
            "ordinal": ordinal,
            "structural_path": structural_path,
            "version_id": str(version_id),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return uuid5(_CHUNK_ID_NAMESPACE, payload)
```

Implement the three frozen/slotted/keyword-only dataclasses exactly as the spec. `DocumentChunk.__post_init__` must validate all fields and raise `DocumentValidationError("chunk_id is not deterministic")` when the supplied ID differs from the function result. Export the five public document names from `packages.domain`.

- [ ] **Step 4: Run focused GREEN and compatibility gates**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_documents.py tests/unit/test_authorization_scope.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/common packages/contracts packages/domain tests/unit/domain/test_documents.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/common packages/contracts packages/domain tests/unit/domain/test_documents.py
```

Expected: all tests pass; Ruff and mypy exit 0.

- [ ] **Step 5: Commit the domain slice**

```bash
git add packages/common packages/contracts/auth.py packages/domain tests/unit/domain/test_documents.py
git commit -m "feat: add immutable document domain"
```

---

### Task 2: Ingestion DocumentStore and Repository Port

**Files:**
- Create: `services/ingestion/__init__.py`
- Create: `services/ingestion/document_store.py`
- Create: `tests/unit/ingestion/__init__.py`
- Create: `tests/unit/ingestion/test_document_store.py`

**Interfaces:**
- Consumes: Task 1 domain types and deterministic IDs.
- Produces: `DocumentRepository` Protocol, `DocumentStore`, `DocumentStoreError`, `DocumentRepositoryError`, `DocumentConflictError`, `DocumentVersionConflictError`, `DocumentChunkConflictError`, `DocumentNotFoundError`, and `DocumentVersionNotFoundError`.

- [ ] **Step 1: Write failing service tests with an in-memory port fake**

Create a deterministic `_MemoryDocumentRepository` storing dictionaries by canonical ID and source/checksum keys. Its methods must use the exact Protocol signatures from the spec and return tuples. Do not use mocks.

Add these primary tests:

```python
def test_register_version_is_idempotent_and_preserves_immutable_record() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    document = _document()
    original = _version(version_id=VERSION_A_ID, checksum="a" * 64)
    retry = replace(original, version_id=VERSION_RETRY_ID)
    assert store.register_document(document) == document
    assert store.register_version(original) == original
    assert store.register_version(retry) == original
    assert store.list_versions(document.document_id) == (original,)


def test_versions_with_different_checksums_coexist() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    document = store.register_document(_document())
    first = store.register_version(_version(checksum="a" * 64))
    second = store.register_version(
        _version(version_id=VERSION_B_ID, checksum="b" * 64)
    )
    assert store.list_versions(document.document_id) == (first, second)
```

Add tests that:

- retry the same source identity with a conflicting ID or title and expect exact `DocumentConflictError("document source identity conflicts")`;
- retry a checksum with changed `source_uri`, timestamp, security level, ship, project, or department and expect exact `DocumentVersionConflictError("document version metadata conflicts")`;
- register a Version before its Document and expect `DocumentNotFoundError("document does not exist")` with zero writes;
- add Chunks before their Version and expect `DocumentVersionNotFoundError("document version does not exist")` with zero writes;
- reject a mixed-version batch and duplicate Chunk IDs/locations with `DocumentChunkConflictError("document chunk batch conflicts")`;
- accept one valid tuple and return it from `list_chunks` unchanged;
- assert `DocumentStore` and `DocumentRepository` expose no `update`, `delete`, `upsert`, or `commit` member.

- [ ] **Step 2: Run service tests to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/ingestion/test_document_store.py -v
```

Expected: collection ERROR because `services.ingestion.document_store` does not exist.

- [ ] **Step 3: Implement the Protocol, errors, and service**

Use `typing.Protocol` and the exact method signatures in spec section 5. Implement registration checks in this order:

```python
def register_document(self, document: Document) -> Document:
    by_id = self._repository.get_document(document.document_id)
    by_source = self._repository.find_document(
        document.source_system, document.source_id
    )
    if by_id is None and by_source is None:
        self._repository.insert_document(document)
        return document
    if by_id == document and by_source == document:
        return document
    raise DocumentConflictError("document source identity conflicts")
```

`register_version` must first require the Document, then inspect both version ID and `(document_id, checksum)`. Compare retries with a private payload tuple excluding only `version_id`; return the stored checksum match when payloads match, otherwise raise the fixed conflict.

`add_chunks` must return immediately for an empty tuple. For a non-empty tuple, require the Version, require every `chunk.version_id == version_id`, and reject duplicate `chunk_id` or `(version_id, structural_path, ordinal)` values before exactly one `insert_chunks` call.

All read methods delegate and return immutable tuples. Export public names from `services/ingestion/__init__.py`.

- [ ] **Step 4: Run focused GREEN and static checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/ingestion/test_document_store.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check services/ingestion tests/unit/ingestion
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy services/ingestion tests/unit/ingestion
```

Expected: all pass.

- [ ] **Step 5: Commit the service slice**

```bash
git add services/ingestion tests/unit/ingestion
git commit -m "feat: add immutable document store service"
```

---

### Task 3: SQLAlchemy Metadata and Alembic Revision 0003

**Files:**
- Create: `infra/postgres/document_models.py`
- Create: `infra/postgres/migrations/versions/20260819_0003_create_documents.py`
- Create: `tests/integration/test_document_versions.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `infra/postgres/migrations/env.py`
- Modify: `tests/integration/test_domain_repository.py`
- Modify: `tests/integration/test_entity_alias_repository.py`

**Interfaces:**
- Consumes: existing `Base`, `ShipModel`, migration head `20260818_0002`, and guarded integration fixtures.
- Produces: `DocumentModel`, `DocumentVersionModel`, `DocumentChunkModel`, and Alembic head `20260819_0003`.

- [ ] **Step 1: Write failing metadata tests**

Create `tests/integration/test_document_versions.py` and assert exact table columns:

```python
def test_document_metadata_declares_version_and_chunk_constraints() -> None:
    from infra.postgres import Base

    assert {"documents", "document_versions", "document_chunks"} <= set(
        Base.metadata.tables
    )
    assert {column.name for column in Base.metadata.tables["documents"].columns} == {
        "document_id", "source_system", "source_id", "title"
    }
    assert {
        column.name
        for column in Base.metadata.tables["document_versions"].columns
    } == {
        "version_id", "document_id", "checksum", "source_uri",
        "source_updated_at", "security_level", "ship_id", "project_id",
        "department",
    }
    assert {
        column.name for column in Base.metadata.tables["document_chunks"].columns
    } == {
        "chunk_id", "version_id", "structural_path", "ordinal",
        "normalized_text", "page", "section",
    }
```

Assert named unique/check/foreign-key constraints and indexes exactly:

- `uq_documents_source_identity`;
- `uq_document_versions_document_checksum`;
- `uq_document_chunks_structural_location`;
- `ck_documents_source_system`, `ck_documents_source_id`, `ck_documents_title`;
- `ck_document_versions_checksum`, `ck_document_versions_source_uri`, `ck_document_versions_security_level`, `ck_document_versions_department`;
- `ck_document_chunks_path_elements`, `ck_document_chunks_ordinal`, `ck_document_chunks_text`, `ck_document_chunks_page`, `ck_document_chunks_section`;
- FKs `documents`, `ships`, and `document_versions` with names from the spec;
- indexes on every ACL/filter column specified by the spec.

- [ ] **Step 2: Run metadata test to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py::test_document_metadata_declares_version_and_chunk_constraints -v
```

Expected: FAIL because the new tables are absent from `Base.metadata`.

- [ ] **Step 3: Implement SQLAlchemy models and metadata registration**

Use `PostgreSQLUUID(as_uuid=True)`, `SmallInteger`, `Text`, `Integer`, `DateTime(timezone=True)`, and `ARRAY(Text)`. Map `structural_path` as `Mapped[list[str]]` and convert only in the repository boundary. The path check must be:

```sql
array_position(structural_path, NULL) IS NULL
AND array_position(structural_path, '') IS NULL
```

Use these foreign-key names:

```text
fk_document_versions_document_id
fk_document_versions_ship_id
fk_document_chunks_version_id
```

Import the document model module from `infra.postgres.__init__`. In Alembic `env.py`, add `from infra.postgres import document_models as _document_models` before assigning `target_metadata` so direct migration invocation registers all tables.

- [ ] **Step 4: Run metadata test GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Write migration-head and empty-upgrade RED tests**

Add:

```python
def test_document_migration_is_current_head(migrated_engine: Engine) -> None:
    assert {"documents", "document_versions", "document_chunks"} <= set(
        inspect(migrated_engine).get_table_names()
    )
    with migrated_engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260819_0003"
```

Update only the two existing intentional current-head assertions in
`test_domain_repository.py` and `test_entity_alias_repository.py` to
`20260819_0003`.

- [ ] **Step 6: Run migration tests to verify RED**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py::test_document_migration_is_current_head -v
```

Expected: ERROR or FAIL because revision `20260819_0003` does not exist.

- [ ] **Step 7: Create and review the exact migration**

Create a linear revision with:

```python
revision: str = "20260819_0003"
down_revision: str | Sequence[str] | None = "20260818_0002"
```

The upgrade creates `documents`, `document_versions`, and `document_chunks` in that order with every column, named constraint, FK, unique constraint, and index defined above. The downgrade drops Chunk indexes/table, Version indexes/table, then Documents. Do not edit earlier revisions.

- [ ] **Step 8: Run migration GREEN, offline SQL, and static gates**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py::test_document_migration_is_current_head tests/integration/test_domain_repository.py::test_migration_upgrades_an_empty_postgresql_database tests/integration/test_entity_alias_repository.py::test_alias_migration_is_current_head -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check infra/postgres tests/integration/test_document_versions.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy infra/postgres tests/integration/test_document_versions.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py
```

Expected: tests pass with zero skips; offline SQL contains all three CREATE TABLE statements; Ruff/mypy pass.

- [ ] **Step 9: Commit the schema slice**

```bash
git add infra/postgres/document_models.py infra/postgres/migrations infra/postgres/migrations/env.py infra/postgres/__init__.py tests/integration/test_document_versions.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py
git commit -m "feat: add document schema migration"
```

---

### Task 4: PostgreSQL Repository, Version Coexistence, and Recovery

**Files:**
- Create: `infra/postgres/document_repository.py`
- Modify: `infra/postgres/__init__.py`
- Modify: `tests/integration/test_document_versions.py`

**Interfaces:**
- Consumes: Task 2 `DocumentRepository` Protocol and Task 3 models/migration.
- Produces: `PostgresDocumentRepository` structurally satisfying the port and complete PostgreSQL acceptance behavior.

- [ ] **Step 1: Write failing round-trip and coexistence test**

Use one synthetic Ship inserted by `DomainRepository`, then:

```python
def test_document_versions_and_chunks_round_trip_and_coexist(
    migrated_session: Session,
) -> None:
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    store = DocumentStore(repository)
    document = store.register_document(_document())
    first = store.register_version(_version())
    second = store.register_version(
        replace(
            _version(),
            version_id=VERSION_B_ID,
            checksum="b" * 64,
            source_uri="s3://synthetic-documents/rule-b.pdf",
            source_updated_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
            security_level=SecurityLevel.CONFIDENTIAL,
        )
    )
    chunks = (_chunk(first.version_id, ("Chapter 1",), 0),)
    store.add_chunks(first.version_id, chunks)
    assert store.get_document(document.document_id) == document
    assert store.list_versions(document.document_id) == (first, second)
    assert store.list_chunks(first.version_id) == chunks
    assert first.ship_id == SHIP_ID
    assert first.project_id == PROJECT_ID
    assert first.department == "Synthetic Engineering"
```

- [ ] **Step 2: Run round-trip test to verify RED**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py::test_document_versions_and_chunks_round_trip_and_coexist -v
```

Expected: collection ERROR because `PostgresDocumentRepository` does not exist.

- [ ] **Step 3: Implement the repository adapter**

Implement exact domain/model conversion functions. Convert `SecurityLevel` to/from its integer value and `structural_path` tuple/list at the boundary. Wrap each single insert and the whole Chunk tuple in `Session.begin_nested()`, call `flush()`, catch only `IntegrityError`, and raise:

```python
raise DocumentRepositoryError(
    "document record violates persistence constraints"
) from None
```

When stored model reconstruction raises `DocumentValidationError` or `ValueError`, raise:

```python
raise DocumentRepositoryError("stored document record is invalid") from None
```

Use SQLAlchemy `select`; version order is `(source_updated_at, version_id)` and Chunk order is `(structural_path, ordinal, chunk_id)`. Never call commit.

- [ ] **Step 4: Run round-trip GREEN**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Add transaction, constraint, atomicity, and corruption tests**

Add exact behaviors:

1. register, call `migrated_session.rollback()`, and assert Document is absent;
2. duplicate source identity and duplicate per-Document checksum raise the fixed `DocumentRepositoryError` without rejected values and leave the first rows unchanged;
3. Version with missing Document/Ship FK fails safely;
4. a direct `insert_chunks` tuple containing one valid Version Chunk and one missing-Version Chunk rolls back both, and `select(literal(1))` proves Session usability;
5. direct SQLAlchemy insertion of a structurally valid row with a random nondeterministic `chunk_id` is accepted by PostgreSQL but `list_chunks` raises `DocumentRepositoryError("stored document record is invalid")`;
6. database checks reject uppercase/malformed checksum, out-of-range security level, invalid ordinal/page, blank text/section/department, and null/empty path elements;
7. exact retry through `DocumentStore` returns the first immutable Version and a metadata conflict raises without inserting a third version.

Run each new node once when written; record whether it is RED for missing adapter behavior or immediate characterization of an already implemented invariant.

- [ ] **Step 6: Run repository and adjacent integration gates**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check infra/postgres/document_repository.py tests/integration/test_document_versions.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy infra/postgres/document_repository.py tests/integration/test_document_versions.py
```

Expected: all tests pass with zero skips; Ruff/mypy pass.

- [ ] **Step 7: Commit the repository slice**

```bash
git add infra/postgres/document_repository.py infra/postgres/__init__.py tests/integration/test_document_versions.py
git commit -m "feat: persist immutable document versions"
```

---

### Task 5: Public Documentation and Complete Definition-of-Done Gate

**Files:**
- Modify: `docs/03-knowledge-system.md`
- Modify: `infra/postgres/README.md`
- Modify only if a verified Task 009 defect appears: Task 009 files listed above.

**Interfaces:**
- Consumes: completed public domain/service/repository contracts and migration `20260819_0003`.
- Produces: documented public behavior and final Task 009 verification evidence.

- [ ] **Step 1: Update knowledge-system documentation**

Document these exact rules in `docs/03-knowledge-system.md`:

- Document is a stable logical source identity;
- DocumentVersion is immutable and uniquely identified per Document/checksum;
- Version carries source URI/time and ship/project/department/security ACL;
- identical retries return the stored version only when immutable metadata agrees;
- Chunk ID is UUIDv5 over canonical JSON of version/path/ordinal;
- an empty structural path is reserved for unstructured fallback;
- Chunks inherit ACL through Version;
- embeddings remain Task 014 scope.

- [ ] **Step 2: Update PostgreSQL operator documentation**

Add revision `20260819_0003`, its parent, the three tables, caller transaction ownership, duplicate/conflict behavior, and this exact guarded command:

```bash
TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  python -m pytest tests/integration/test_document_versions.py -v
```

- [ ] **Step 3: Run focused acceptance gates**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_document_versions.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
```

Expected: all focused tests pass, integration has zero skips, and offline SQL includes revision `20260819_0003` plus all three tables.

- [ ] **Step 4: Run full quality gate**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
git diff --check 7aecfd3...HEAD
git diff --name-only 7aecfd3...HEAD
```

Expected: dependency check, complete pytest, Ruff, and mypy pass; diff hygiene is clean; changed files are restricted to the approved spec/plan and Task 009 paths.

- [ ] **Step 5: Verify acceptance criteria explicitly**

Record evidence:

1. immutable frozen Version plus no update/delete service/repository APIs;
2. stable path-boundary-safe UUIDv5 Chunk IDs and repository reconstruction;
3. exact ship/project/department/security round trip and database constraints;
4. two checksums coexist for one Document while identical checksum retry deduplicates safely;
5. no real data, secrets, production access, parser, chunker, embedding, or Task 010 changes.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/03-knowledge-system.md infra/postgres/README.md
git commit -m "docs: document immutable knowledge records"
```

- [ ] **Step 7: Request task and whole-branch review**

Run a Task 009 spec-compliance review against `AGENTS.md`, the Task file, and approved spec, then a whole-branch code/security review. Resolve verified findings with focused TDD and rerun the full gate after every material correction. Do not merge, push, or begin Task 010 without user authorization.
