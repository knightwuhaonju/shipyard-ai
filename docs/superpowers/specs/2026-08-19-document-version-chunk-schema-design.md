# Task 009 Document, Version, and Chunk Schema Design

## 1. Purpose and scope

Task 009 introduces the durable metadata boundary for the Shipyard AI
knowledge plane:

```text
Document -> immutable DocumentVersion -> deterministic DocumentChunk
```

`Document` is the stable logical identity of an externally sourced document.
`DocumentVersion` is one immutable content and authorization snapshot.
`DocumentChunk` is a reproducible structural location inside one version.

This task owns domain contracts, ingestion service behavior, PostgreSQL
models, a repository adapter, and Alembic revision `20260819_0003`. It does
not parse files, perform OCR, implement structure-aware chunking, store
embeddings, build retrieval indexes, expose an API, or begin Task 010.

## 2. Architecture boundaries

- Original documents and their immutable versions remain the source of truth
  for rules, manuals, SOPs, and signed records.
- Domain records remain frozen dataclasses and do not import FastAPI,
  Pydantic, SQLAlchemy, PostgreSQL, object-store SDKs, or model SDKs.
- `services.ingestion.document_store` owns the application service and its
  repository port. It imports domain/common contracts, never infrastructure.
- `infra.postgres.document_repository` implements the port and is the only
  new code that maps document domain types to SQLAlchemy models.
- The service and repository are insert/read-only. They expose no update,
  delete, upsert, or commit operation.
- Callers own the SQLAlchemy transaction. Repository operations use nested
  savepoints only to preserve Session usability after an integrity failure.
- All tests use deterministic synthetic records and the guarded
  `shipyard_ai_test` PostgreSQL database. They make no network or external
  model calls.

The dependency direction is:

```text
services.ingestion -> packages.domain / packages.common
infra.postgres -> services.ingestion port / packages.domain
```

No production package imports test fixtures.

## 3. Shared security-level primitive

`SecurityLevel` currently lives in `packages.contracts.auth`, whose module is
Pydantic-based. Importing it into the domain would make the framework-
independent domain depend on a transport-contract package.

Task 009 moves the enum implementation to `packages/common/security.py`:

```python
class SecurityLevel(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
```

`packages.contracts.auth` imports and re-exports the same class, so existing
imports from `packages.contracts` and `packages.contracts.auth` remain fully
compatible. `packages.common` also exports it. This is a targeted dependency
correction, not a new authorization policy.

## 4. Domain contracts

All document domain types live in `packages/domain/documents.py` and are
exported from `packages.domain`.

### 4.1 Document

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Document:
    document_id: UUID
    source_system: str
    source_id: str
    title: str
```

- `document_id` is the internal canonical UUID.
- `(source_system, source_id)` is the external logical identity and is unique
  in PostgreSQL.
- Source IDs never replace the canonical UUID.
- Required strings are non-blank after surrounding whitespace is ignored.
- Version-specific source time, URI, checksum, and ACL do not live on this
  stable identity.

### 4.2 DocumentVersion

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentVersion:
    version_id: UUID
    document_id: UUID
    checksum: str
    source_uri: str
    source_updated_at: datetime
    security_level: SecurityLevel
    ship_id: UUID | None = None
    project_id: UUID | None = None
    department: str | None = None
```

- `checksum` is exactly 64 lowercase hexadecimal characters representing
  SHA-256 output. Algorithm negotiation is outside V1.
- `source_uri` is required non-blank text. The domain does not assume a
  filesystem, HTTP, or object-store URI scheme.
- `source_updated_at` must be timezone-aware.
- `security_level` must be the shared ordered enum.
- `ship_id`, `project_id`, and `department` are optional ACL metadata.
- A present `department` is non-blank.
- `(document_id, checksum)` is unique. The same checksum can exist under two
  different logical Documents without sharing authorization metadata.

The service has no mutation operation. A repeated registration of the same
Document and checksum returns the stored immutable version only when every
non-ID version field matches. A repeated checksum with different source or
ACL metadata raises a safe `DocumentVersionConflictError`; disagreement is
never silently overwritten.

### 4.3 DocumentChunk and deterministic IDs

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentChunk:
    chunk_id: UUID
    version_id: UUID
    structural_path: tuple[str, ...]
    ordinal: int
    normalized_text: str
    page: int | None = None
    section: str | None = None

def document_chunk_id(
    version_id: UUID,
    structural_path: tuple[str, ...],
    ordinal: int,
) -> UUID: ...
```

The function uses UUIDv5 with a fixed, checked-in namespace and a canonical
JSON payload containing the lowercase version UUID, path array, and ordinal.
Canonical JSON uses UTF-8 concepts, `ensure_ascii=False`, sorted object keys,
and compact separators. JSON array boundaries prevent delimiter collisions
such as `("a/b",)` versus `("a", "b")`.

- `structural_path` is an immutable tuple whose elements are non-blank.
- An empty path is allowed for the Task 011 unstructured fallback.
- `ordinal` is an integer greater than or equal to zero; booleans are rejected.
- A present `page` is a positive integer; booleans are rejected.
- A present `section` and `normalized_text` are non-blank.
- `DocumentChunk.__post_init__` requires `chunk_id` to equal
  `document_chunk_id(version_id, structural_path, ordinal)`.
- `(version_id, structural_path, ordinal)` is unique in PostgreSQL.

Embedding columns are intentionally absent; Task 014 owns pgvector storage.

## 5. Ingestion service and repository port

`services/ingestion/document_store.py` defines framework-independent service
errors, a structural repository `Protocol`, and `DocumentStore`.

The port provides:

```python
class DocumentRepository(Protocol):
    def insert_document(self, document: Document) -> None: ...
    def get_document(self, document_id: UUID) -> Document | None: ...
    def find_document(
        self, source_system: str, source_id: str
    ) -> Document | None: ...
    def insert_version(self, version: DocumentVersion) -> None: ...
    def get_version(self, version_id: UUID) -> DocumentVersion | None: ...
    def find_version(
        self, document_id: UUID, checksum: str
    ) -> DocumentVersion | None: ...
    def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]: ...
    def insert_chunks(self, chunks: tuple[DocumentChunk, ...]) -> None: ...
    def list_chunks(self, version_id: UUID) -> tuple[DocumentChunk, ...]: ...
```

`DocumentStore` exposes:

```python
register_document(document: Document) -> Document
register_version(version: DocumentVersion) -> DocumentVersion
add_chunks(version_id: UUID, chunks: tuple[DocumentChunk, ...]) -> None
get_document(document_id: UUID) -> Document | None
get_version(version_id: UUID) -> DocumentVersion | None
list_versions(document_id: UUID) -> tuple[DocumentVersion, ...]
list_chunks(version_id: UUID) -> tuple[DocumentChunk, ...]
```

Behavior:

- exact retries of a Document source identity return the stored Document;
- a source identity with conflicting canonical ID or title raises
  `DocumentConflictError`;
- a new checksum is inserted as another immutable version;
- `register_version` first requires the referenced Document to exist and
  otherwise raises value-safe `DocumentNotFoundError`;
- an identical version retry may use another proposed `version_id`, but all
  non-ID fields must match; the stored version is returned;
- a repeated checksum with different source/ACL metadata raises
  `DocumentVersionConflictError`;
- `add_chunks` requires every chunk to use the supplied `version_id`, rejects
  duplicate IDs or structural locations in the batch, and delegates one
  atomic tuple insertion;
- `add_chunks` first requires the referenced Version to exist and otherwise
  raises value-safe `DocumentVersionNotFoundError`;
- the domain already proves each Chunk ID is deterministic;
- repository errors have fixed messages and never contain source IDs,
  checksum values, URIs, department names, or normalized text.

There is no method capable of changing a stored version. This absence plus
frozen domain values is the Task 009 service immutability contract.

## 6. PostgreSQL schema

SQLAlchemy models live in `infra/postgres/document_models.py` and reuse the
existing `Base` from `infra.postgres.models`.

### 6.1 `documents`

| Column | Type | Constraint |
|---|---|---|
| `document_id` | UUID | primary key |
| `source_system` | TEXT | non-null, non-blank |
| `source_id` | TEXT | non-null, non-blank |
| `title` | TEXT | non-null, non-blank |

Unique constraint: `(source_system, source_id)`.

### 6.2 `document_versions`

| Column | Type | Constraint |
|---|---|---|
| `version_id` | UUID | primary key |
| `document_id` | UUID | FK `documents.document_id`, non-null |
| `checksum` | TEXT | non-null, lowercase SHA-256 check |
| `source_uri` | TEXT | non-null, non-blank |
| `source_updated_at` | TIMESTAMPTZ | non-null |
| `security_level` | SMALLINT | non-null, 0 through 3 |
| `ship_id` | UUID | nullable FK `ships.id` |
| `project_id` | UUID | nullable, no FK until Project exists |
| `department` | TEXT | nullable, non-blank when present |

Unique constraint: `(document_id, checksum)`. Indexes cover `document_id`,
`ship_id`, `project_id`, `department`, and `security_level` for later ACL-
first retrieval.

### 6.3 `document_chunks`

| Column | Type | Constraint |
|---|---|---|
| `chunk_id` | UUID | primary key |
| `version_id` | UUID | FK `document_versions.version_id`, non-null |
| `structural_path` | TEXT[] | non-null, default-free |
| `ordinal` | INTEGER | non-null, at least 0 |
| `normalized_text` | TEXT | non-null, non-blank |
| `page` | INTEGER | nullable, positive when present |
| `section` | TEXT | nullable, non-blank when present |

Unique constraint: `(version_id, structural_path, ordinal)`. Indexes cover
`version_id` and `page`. PostgreSQL rejects null arrays and null elements;
domain construction rejects blank/whitespace elements, and repository reads
reconstruct the domain type and verify both element validity and deterministic
`chunk_id` values. This avoids introducing a database function solely for a
TEXT-array whitespace check.

Foreign keys use default restrictive deletion. Task 009 provides no deletion
path and does not cascade removal of evidence.

## 7. Migration and metadata registration

Alembic revision `20260819_0003_create_documents.py` has the sole parent
`20260818_0002`. Upgrade order is Documents, DocumentVersions, then
DocumentChunks; downgrade reverses that order.

Because document models are in a separate module, `infra.postgres` exports
them and Alembic `env.py` explicitly imports that module before assigning
`Base.metadata`. Tests verify no schema table is missing from metadata and
offline SQL contains all three tables and constraints.

Existing tests that intentionally assert the current migration head change
from `20260818_0002` to `20260819_0003`; the Task 007 migration remains in the
chain and is not rewritten.

## 8. PostgreSQL repository behavior

`infra/postgres/document_repository.py` maps only the three Task 009 domain
types. It:

- accepts a caller-owned `Session`;
- inserts one Document or DocumentVersion inside a nested savepoint;
- inserts a tuple of Chunks inside one outer nested savepoint so the batch is
  atomic;
- flushes but never commits;
- translates integrity failures to the port's fixed
  `DocumentRepositoryError`;
- reconstructs frozen domain objects on reads, causing corrupt deterministic
  Chunk IDs or invalid stored values to fail safely;
- orders versions by `source_updated_at`, then `version_id`;
- orders chunks by `structural_path`, `ordinal`, then `chunk_id`;
- returns immutable tuples.

No raw SQL, generated SQL, production source connection, update, delete,
upsert, or object-store access is added.

## 9. Validation and failure behavior

Domain errors are `DocumentValidationError` with fixed field-oriented text.
Service conflicts use `DocumentConflictError`,
`DocumentVersionConflictError`, `DocumentChunkConflictError`,
`DocumentNotFoundError`, or `DocumentVersionNotFoundError`. PostgreSQL
constraint failures and corrupt stored rows use `DocumentRepositoryError`.

Errors never interpolate rejected values. In particular, no exception message
contains a source URI, checksum, normalized chunk text, department, database
URL, or environment value. A repository failure rolls back its savepoint and
leaves the caller Session usable.

Missing timestamps, naive timestamps, malformed checksums, unknown security
levels, blank ACL fields, invalid structural locations, nondeterministic IDs,
wrong-version Chunk batches, and database constraint violations are explicit
failures. The system never infers or broadens ACL values.

## 10. Testing strategy

### Unit tests

`tests/unit/domain/test_documents.py` covers:

- valid immutable domain records;
- checksum, timestamp, ACL, text, page, ordinal, and tuple-path validation;
- stable UUIDv5 Chunk IDs across repeated calls;
- delimiter/path collision resistance;
- rejection of caller-supplied nondeterministic Chunk IDs; and
- public exports.

`tests/unit/ingestion/test_document_store.py` uses a deterministic in-memory
fake repository and covers:

- idempotent Document and Version retries;
- multiple checksums coexisting for one Document;
- conflicts on changed stable or immutable metadata;
- missing parent Document and Version rejection before port writes;
- no update/delete methods in the public service/port;
- wrong-version and duplicate Chunk batch rejection; and
- immutable tuple results.

No unit test connects to a database, network, object store, or model.

### Integration tests

`tests/integration/test_document_versions.py` uses synthetic values and the
existing guarded migrated Session to cover:

- metadata/table/constraint/index declarations;
- migration chain head `20260819_0003` and empty-database upgrade;
- Document, two coexisting versions, and deterministic Chunks round trips;
- ship/project/department/security metadata preservation;
- caller transaction ownership;
- duplicate/source/checksum/FK/check failures;
- atomic Chunk batch rollback and reusable Session;
- safe repository error messages;
- offline migration SQL; and
- compatibility with the existing domain and alias tables.

The final gate runs the focused unit and integration modules with zero skips,
the relevant existing migration/security suites, the complete pytest suite,
Ruff, mypy, dependency check, offline Alembic SQL, and diff hygiene.

## 11. Documentation

`docs/03-knowledge-system.md` records the exact immutable metadata and Chunk
ID rule. `infra/postgres/README.md` documents revision `20260819_0003`, the
three tables, transaction ownership, duplicate behavior, and the guarded test
command.

This design document is the required cross-subsystem decision record for the
domain/service/infrastructure boundary and shared security enum move.

## 12. Expected files

Create:

- `packages/common/security.py`
- `packages/domain/documents.py`
- `services/ingestion/__init__.py`
- `services/ingestion/document_store.py`
- `infra/postgres/document_models.py`
- `infra/postgres/document_repository.py`
- `infra/postgres/migrations/versions/20260819_0003_create_documents.py`
- `tests/unit/domain/test_documents.py`
- `tests/unit/ingestion/__init__.py`
- `tests/unit/ingestion/test_document_store.py`
- `tests/integration/test_document_versions.py`

Modify:

- `packages/common/__init__.py`
- `packages/contracts/auth.py`
- `packages/domain/__init__.py`
- `infra/postgres/__init__.py`
- `infra/postgres/migrations/env.py`
- `infra/postgres/README.md`
- `docs/03-knowledge-system.md`
- `tests/integration/test_domain_repository.py`
- `tests/integration/test_entity_alias_repository.py`

No application API, parser, chunker, OCR adapter, retrieval implementation,
embedding column, production connector, Task 010 file, or later Task is
created or modified.

## 13. Acceptance mapping

- DocumentVersion immutability: frozen dataclass, insert/read-only service and
  repository contracts, immutable duplicate semantics, no update/delete API.
- Deterministic Chunk IDs: fixed namespace UUIDv5 over canonical JSON of
  version, structural path, and ordinal; domain and integration validation.
- Ship/project/department/security metadata: immutable Version fields,
  database constraints/indexes, and exact round-trip coverage.
- Version coexistence: unique per-Document checksum, two different checksums
  round-trip together while identical retries deduplicate safely.
