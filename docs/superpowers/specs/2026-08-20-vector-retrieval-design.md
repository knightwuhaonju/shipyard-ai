# Task 014 Vector Retrieval Design

**Date:** 2026-08-20
**Status:** Approved in chat; awaiting written-spec review
**Scope:** Task 014 only

## 1. Objective

Add replaceable embedding generation, deterministic fake embeddings, immutable
pgvector storage, and ACL-filtered vector retrieval over the document chunks
created by Tasks 009-011. Task 014 returns the existing
`KnowledgeEvidence` contract with a vector score and does not implement hybrid
retrieval, reranking, an API, Wiki search, Agent behavior, or Task 015.

Original documents and immutable document versions remain authoritative.
Embeddings and vector scores are derived retrieval artifacts, never a source
of truth.

## 2. Approved approach

Task 014 uses a separate, model-versioned `document_chunk_embeddings` table.
It does not add an embedding column to `document_chunks`.

The initial database embedding profile is:

```text
model_id: fake-deterministic-v1
dimension: 8
distance: cosine
index: HNSW / vector_cosine_ops
```

An immutable chunk may have one embedding per model ID. A retry must not
overwrite a stored embedding. Re-embedding uses a new model ID. A future model
with a different dimension requires an explicit schema migration, index
rebuild, and re-embedding operation; changing a runtime value alone must fail
closed.

This is intentionally narrower than a dimensionless multi-model table with
per-model expression indexes. pgvector supports that pattern, but it adds
profile/index lifecycle management that Task 014 does not need. The official
pgvector documentation supports fixed-dimension `VECTOR(n)`, cosine distance,
and HNSW `vector_cosine_ops` indexes:

- https://github.com/pgvector/pgvector
- https://github.com/pgvector/pgvector-python

## 3. Architecture and dependency constraints

The dependency direction remains:

```text
services/model_gateway -> standard library only
services/retrieval -> packages/contracts + services/model_gateway
adapters/embedding -> services/model_gateway
infra/postgres -> packages/contracts + service ports + PostgreSQL models
```

Forbidden dependencies include:

- domain or service code importing SQLAlchemy, pgvector, FastAPI, or a model
  SDK;
- embedding adapters importing PostgreSQL or retrieval infrastructure;
- vector retrieval connecting to a real model provider in tests;
- an Agent, API, parser, chunker, Wiki, reranker, or hybrid-retrieval
  dependency;
- model-provided identity or authorization scope;
- vector storage replacing document/version provenance.

The PostgreSQL lexical and vector adapters share a small infrastructure-owned
support module for canonical scope UUIDs, the exact four ACL predicates,
request filters, and evidence excerpts. Task 014 may extract the already
tested lexical helpers into `infra/postgres/retrieval_support.py`, but it may
not change lexical behavior. The complete Task 013 retrieval suite protects
that extraction.

## 4. Embedding service contract

`services/model_gateway/embedding.py` owns the vendor-independent boundary.

### 4.1 Embedding profile

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingProfile:
    model_id: str
    dimension: int
```

Validation is exact and value-free:

- `model_id` is an exact non-blank, NUL-free string of at most 128 code points;
- `dimension` is an exact positive integer from 1 through 2,000;
- subclasses, booleans, and coerced values are rejected.

The 2,000 limit matches pgvector's indexed `vector` dimensional limit. The
profile is explicit constructor configuration, not a hidden adapter constant.
Unit tests use more than one valid dimension to prove that the model gateway
is configuration-controlled. PostgreSQL storage accepts only its migrated
eight-dimensional profile and rejects a mismatch before executing SQL.

### 4.2 Port and gateway

```python
class EmbeddingPort(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]: ...


class EmbeddingGateway:
    def embed(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]: ...
```

`EmbeddingAdapterError` is the typed failure an adapter uses after translating
provider/library errors. Its own message is never exposed by the gateway.

The gateway validates both sides of the adapter boundary:

- input is an exact, non-empty tuple with at most 128 texts;
- every text is an exact non-blank, NUL-free string of at most 2,000 code
  points;
- output is an exact tuple with the same number of vectors;
- every vector is an exact tuple of the configured dimension;
- every element is an exact finite float; booleans, integers, NaN, and
  infinities are rejected;
- every vector has a non-zero norm;
- the gateway does not silently resize or normalize adapter output.

Invalid caller input raises `EmbeddingValidationError` with exactly
`invalid embedding request`. A typed adapter-reported failure or invalid
adapter output raises `EmbeddingUnavailableError` with exactly
`embedding unavailable`, using `from None` so provider or input details cannot
escape. The gateway catches only the typed adapter failure, not arbitrary
programming exceptions; each real adapter remains responsible for translating
its provider/library failures at its own boundary.

### 4.3 Deterministic fake

`FakeEmbeddingAdapter` receives an `EmbeddingProfile` and an explicit mapping
from text to immutable vectors. It copies and validates configuration at
construction, records calls, returns mapped vectors deterministically, and
raises only the typed adapter failure for unknown text. The gateway translates
that failure to the fixed embedding-unavailable error. The fake has no network,
filesystem, database, environment, clock, random, or model-SDK behavior.

## 5. PostgreSQL storage

### 5.1 Dependency

Add the official Python package:

```text
pgvector>=0.4,<0.6
```

The resolved version is committed to both lock files. No NumPy dependency is
required for the SQLAlchemy list-of-floats path.

### 5.2 Table

Revision `20260820_0005` creates the `vector` extension if absent and creates:

```text
document_chunk_embeddings
  chunk_id          UUID       NOT NULL FK document_chunks(chunk_id)
  embedding_model   TEXT       NOT NULL
  embedding         VECTOR(8)  NOT NULL
  PRIMARY KEY (chunk_id, embedding_model)
  CHECK (btrim(embedding_model) <> '')
  CHECK (vector_norm(embedding) > 0)
```

Indexes:

- B-tree on `embedding_model` for exact active-profile filtering;
- HNSW on `embedding vector_cosine_ops` for nearest-neighbor ordering.

The migration is deterministic: dimension 8 is part of the committed schema,
not read from an environment variable. Downgrade drops Task 014's table and
indexes but deliberately leaves the potentially shared `vector` extension
installed.

SQLAlchemy metadata uses `pgvector.sqlalchemy.VECTOR(8)` and declares the same
constraints and indexes. Metadata, online migration, offline SQL, downgrade,
single-head, and database constraint tests must agree.

### 5.3 Persistence adapter

`PostgresEmbeddingRepository` uses a caller-owned `Session` and an explicit
storage-compatible `EmbeddingProfile`. It exposes an insert-only operation:

```python
insert(chunk_id: UUID, embedding: tuple[float, ...]) -> None
```

It validates the exact UUID and vector again at the infrastructure boundary,
uses a nested transaction so the caller retains transaction ownership, and
never commits. A duplicate chunk/model record, missing chunk, invalid vector,
or database constraint failure raises `EmbeddingPersistenceError` with exactly
`embedding record violates persistence constraints` and no values or driver
details. It does not update or overwrite an existing embedding.

## 6. Vector retrieval service

`services/retrieval/vector.py` owns the validated orchestration boundary.

```python
class VectorSearchPort(Protocol):
    def search(
        self,
        query: str,
        query_embedding: tuple[float, ...],
        profile: EmbeddingProfile,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]: ...


class VectorRetriever:
    def retrieve(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int = 10,
    ) -> list[KnowledgeEvidence]: ...
```

The retriever receives an `EmbeddingGateway` and a `VectorSearchPort`. It:

1. applies the same exact query, scope, filter, and 1-20 limit validation used
   by lexical retrieval;
2. strips the query;
3. embeds exactly one query in exactly one gateway call;
4. passes the trusted scope separately from caller filters;
5. returns the port's evidence list unchanged.

Invalid requests raise `VectorRetrievalValidationError` with exactly
`invalid vector retrieval request` before embedding or SQL. Embedding failure
is translated to `VectorRetrievalError` with exactly
`vector retrieval unavailable`, from no provider context.

Task 014 does not automatically embed chunks during ingestion. The new
gateway and repository are the explicit boundaries a later ingestion job can
orchestrate without changing the document domain contract.

## 7. PostgreSQL vector query

`PostgresVectorSearchAdapter(engine, profile)` stores an `Engine` and the
single active profile. Construction fails with a fixed value-free error if
the profile dimension does not match the migrated database dimension.

It builds one parameterized `SELECT` joining:

```text
document_chunk_embeddings
  -> document_chunks
  -> document_versions
  -> documents
```

The candidate `WHERE` clause contains, before ordering and `LIMIT`:

```text
embedding.embedding_model = profile.model_id
AND version.security_level <= scope.security_level
AND (version.department IS NULL OR version.department IN scope.departments)
AND (version.ship_id IS NULL OR version.ship_id IN scope.allowed_ship_ids)
AND (version.project_id IS NULL OR version.project_id IN scope.allowed_project_ids)
AND optional exact document_type filter
AND optional exact ship_id filter
AND optional exact project_id filter
```

Canonical scope UUID behavior remains identical to lexical retrieval:
canonical lowercase and uppercase UUID text is accepted, malformed or
brace-wrapped text is ignored, and invalid values never broaden access. Null
ACL metadata is global for that dimension; every non-null dimension requires
exact membership; all present dimensions intersect. Filters only narrow the
authorized set and never trigger a fallback query.

## 8. Distance, score, order, and evidence

The SQL distance expression is cosine distance:

```text
embedding <=> query_embedding
```

Results order by:

1. cosine distance ascending;
2. `document_versions.source_updated_at` descending;
3. `document_chunks.chunk_id` ascending.

The final UUID tie-break makes repeated retrieval deterministic. The public
score is:

```text
max(0.0, 1.0 - cosine_distance)
```

Every returned value is finite. Each result sets:

```text
retrieval_score = vector_score
lexical_score = None
rerank_score = None
```

Evidence retains document/version/chunk IDs, title, page, section, source URI,
and an excerpt of at most 2,000 code points. The shared excerpt helper centers
an exact case-insensitive literal occurrence when present and starts at the
beginning for semantic-only matches.

HNSW search is approximate. ACL and profile predicates are still present in
the SQL candidate query, so approximate behavior may reduce recall but can
never authorize a row. Task 014 records filtered approximate-search recall as
a known limitation rather than adding Task 015 fusion behavior.

## 9. Transaction, timeout, and error policy

The vector adapter follows the lexical adapter's database boundary:

```python
with Session(engine) as session, session.begin():
    session.execute(text("SET TRANSACTION READ ONLY"))
    # transaction-local statement_timeout = 2000 ms
    rows = session.execute(statement, parameters).all()
```

It uses a private short-lived session, one read-only transaction, a
transaction-local 2,000 ms timeout, bound query/vector/filter/ACL/limit values,
and a hard public maximum of 20 rows. It emits no insert, update, delete, or
DDL and returns its connection to the pool on success and failure.

Only `SQLAlchemyError` is translated to `VectorRetrievalError` with exactly
`vector retrieval unavailable`, raised `from None`. The message contains no
query, vector, model ID, SQL, credentials, ACL, source identifiers, document
content, or driver details.

## 10. Test design and TDD sequence

Every behavior change follows RED -> minimum GREEN -> focused suite ->
relevant suite -> Ruff -> mypy.

### 10.1 Unit tests

- exact `EmbeddingProfile` validation and immutability;
- input batch, string, count, length, NUL, output count, dimension, element
  type, finite value, and non-zero norm validation;
- fixed safe errors with suppressed cause/context;
- deterministic fake mapping and call recording;
- no external model/network/filesystem/database dependencies;
- vector request exact-type, query, scope, filter, and limit validation;
- embed-once and port-once delegation;
- no port call after invalid request or embedding failure;
- deny-by-default AST dependency guards for model gateway, fake adapter, and
  vector retrieval service.

### 10.2 Migration and persistence integration tests

- `vector` extension, exact table/columns/PK/FK/checks, B-tree index, and HNSW
  cosine index;
- single Alembic head `20260820_0005`;
- online upgrade, offline SQL, downgrade, and extension retention;
- valid eight-dimensional insert;
- wrong dimension, zero vector, duplicate model/chunk, and missing chunk fail
  safely;
- caller transaction ownership and session recovery;
- model-specific coexistence without overwrite.

### 10.3 Retrieval integration and security tests

- primary cross-project zero-leakage vector retrieval;
- security level, department, ship, project, intersection, and global-null
  matrices;
- malformed, uppercase, and brace-wrapped scope UUID behavior;
- document-type, ship, and project filters cannot bypass scope;
- model profile isolation;
- exact independent cosine distance/score oracle;
- limit and deterministic tie ordering;
- exact `KnowledgeEvidence` and semantic-only excerpt behavior;
- bound malicious query/model/vector inputs and no SQL injection;
- candidate SQL contains ACL/profile/filter predicates before order/limit;
- read-only transaction, 2,000 ms timeout, no mutation, unchanged row counts,
  zero checked-out connections, and fixed cause-free database errors;
- architecture import guards and no Task 015 dependency.

All fixtures use synthetic IDs, text, URIs, and vectors. Unit and integration
tests never call an external model.

## 11. Expected files

Create:

- `services/model_gateway/__init__.py`
- `services/model_gateway/embedding.py`
- `adapters/embedding/__init__.py`
- `adapters/embedding/fake.py`
- `services/retrieval/vector.py`
- `infra/postgres/retrieval_support.py`
- `infra/postgres/embedding_repository.py`
- `infra/postgres/vector_retrieval.py`
- `infra/postgres/migrations/versions/20260820_0005_add_vector_retrieval.py`
- `tests/unit/model_gateway/__init__.py`
- `tests/unit/model_gateway/test_embedding.py`
- `tests/unit/retrieval/test_vector_contracts.py`
- `tests/integration/retrieval/test_vector_acl.py`

Modify when directly required:

- `pyproject.toml`
- `requirements.lock`
- `requirements-dev.lock`
- `infra/postgres/document_models.py`
- `infra/postgres/lexical_retrieval.py`
- `infra/postgres/__init__.py`
- `services/retrieval/__init__.py`
- existing migration-head and document metadata tests
- existing lexical import/regression tests for the shared support extraction
- `docs/03-knowledge-system.md`
- `docs/06-security.md`

No application configuration file changes are required in Task 014 because
no runtime composition root exists yet. `EmbeddingProfile` is the explicit
configuration object. Task 016 may bind deployment environment settings to a
profile when it wires the public knowledge API.

## 12. Acceptance mapping

| Task 014 criterion | Design evidence |
|---|---|
| Tests never require an external model | Deterministic mapping fake and strict architecture guards |
| Embedding dimension is configuration-controlled | Explicit immutable `EmbeddingProfile`; multi-dimension unit tests; DB mismatch fails closed |
| ACL is enforced before/with vector query | Shared four-dimension SQL predicates before distance ordering and limit |
| Evidence contains vector score | `retrieval_score == vector_score`, exact provenance, other scores unset |

## 13. Explicit exclusions and known limitations

Task 014 does not implement:

- a real embedding provider;
- automatic ingestion orchestration or background embedding jobs;
- model lifecycle administration or online re-indexing;
- multiple dimensions in one HNSW index;
- hybrid retrieval, reranking, weight fusion, or Task 015;
- API, Wiki, tool, Agent, eval, or UI behavior.

Known V1 limitations:

- the migrated database profile is fixed at eight dimensions;
- changing dimension requires a migration and re-embedding;
- HNSW with authorization filters may return fewer candidates than an exact
  scan, but it cannot widen authorization;
- all authorized immutable versions remain searchable because there is no
  current-version lifecycle marker;
- embeddings remain derived and must be regenerated from authoritative chunk
  text if lost.
