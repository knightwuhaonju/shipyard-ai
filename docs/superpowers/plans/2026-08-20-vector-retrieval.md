# Vector Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, replaceable embedding generation, immutable pgvector storage, and ACL-filtered vector retrieval that returns attributable `KnowledgeEvidence` without starting hybrid retrieval.

**Architecture:** A standard-library-only model-gateway contract validates configured embedding profiles and adapter output. A deterministic mapping fake supplies every test vector. PostgreSQL stores one eight-dimensional vector per chunk/model, while lexical and vector search share exact authorization/filter/excerpt helpers; vector retrieval embeds once and executes one read-only, timeout-bounded, ACL-filtered cosine query.

**Tech Stack:** Python 3.12, dataclasses, Protocol, SQLAlchemy 2.x, Alembic, PostgreSQL 16, pgvector/pgvector-python, Pydantic contracts, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-20-vector-retrieval-design.md`

## Global Constraints

- Implement Task 014 only; do not add hybrid retrieval, reranking, Task 015, API, Wiki, Agent, tool, eval, or UI behavior.
- Original documents and immutable versions remain authoritative; embeddings and scores are derived artifacts.
- Tests use only the deterministic fake and synthetic data; no external model or network call is permitted.
- Initial database profile: model ID `fake-deterministic-v1`, dimension `8`, cosine distance, HNSW `vector_cosine_ops`.
- `EmbeddingProfile` controls model ID and dimension; PostgreSQL adapters fail before SQL when dimension is not 8.
- Changing database dimension requires a new deterministic migration and re-embedding; migrations never read it from the environment.
- Authorization uses security, department, ship, and project predicates in candidate SQL before distance ordering and `LIMIT`.
- Null ACL metadata is global; each non-null dimension requires exact membership; all present dimensions intersect.
- Filters only narrow authorized candidates and never trigger fallback.
- Query/vector/filter values are bound; searches are read-only, use a local 2,000 ms timeout, and return at most 20 rows.
- Fixed errors contain no query, vector, model, SQL, credentials, ACL, identifier, content, or driver detail.
- Add `pgvector>=0.4,<0.6`, resolve `pgvector==0.5.0` in both lock files, and do not add NumPy.
- PostgreSQL tests use only `postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test` through guarded fixtures.
- Preserve and rerun all Task 013 lexical behavior after extracting shared helpers.
- Do not commit `.superpowers/sdd` artifacts.

## File Responsibility Map

- `services/model_gateway/embedding.py`: profile, port, gateway, validation, and fixed errors.
- `adapters/embedding/fake.py`: deterministic text-to-vector mapping fake and call recording.
- `infra/postgres/document_models.py`: `DocumentChunkEmbeddingModel` and pgvector metadata.
- `infra/postgres/embedding_repository.py`: caller-session insert-only persistence.
- `infra/postgres/retrieval_support.py`: shared UUID, ACL/filter, and excerpt helpers.
- `infra/postgres/lexical_retrieval.py`: existing lexical adapter consuming shared support only.
- `services/retrieval/vector.py`: vector request validation and embed-once orchestration.
- `infra/postgres/vector_retrieval.py`: read-only cosine query and evidence assembly.
- `tests/integration/retrieval/test_vector_storage.py`: schema, migration, constraints, repository.
- `tests/integration/retrieval/test_vector_acl.py`: search, score, evidence, ACL, SQL security.

---

### Task 1: Define the embedding profile, gateway, and deterministic fake

**Files:**
- Create: `services/model_gateway/__init__.py`
- Create: `services/model_gateway/embedding.py`
- Create: `adapters/embedding/__init__.py`
- Create: `adapters/embedding/fake.py`
- Create: `tests/unit/model_gateway/__init__.py`
- Create: `tests/unit/model_gateway/test_embedding.py`

**Interfaces:**
- Consumes: standard library only.
- Produces: `EmbeddingProfile`, `EmbeddingPort`, `EmbeddingGateway`, `EmbeddingAdapterError`, `EmbeddingValidationError`, `EmbeddingUnavailableError`, `FakeEmbeddingAdapter`.

- [ ] **Step 1: Write profile and gateway RED tests**

Create future imports and these primary tests before production modules:

```python
def test_gateway_uses_explicit_profile_and_returns_exact_vectors() -> None:
    profile = EmbeddingProfile(model_id="fake-deterministic-v1", dimension=3)
    adapter = FakeEmbeddingAdapter(profile, {"ballast pump": (1.0, 0.0, 0.0)})

    result = EmbeddingGateway(adapter).embed(("ballast pump",))

    assert result == ((1.0, 0.0, 0.0),)
    assert adapter.calls == (("ballast pump",),)
    assert adapter.profile is profile


def test_profile_dimension_is_configuration_controlled() -> None:
    assert EmbeddingProfile(model_id="model-3", dimension=3).dimension == 3
    assert EmbeddingProfile(model_id="model-8", dimension=8).dimension == 8
```

Add literal rejection tables for model ID non-string/subclass, blank, NUL,
and 129 characters; dimension `True`, `1.0`, `0`, `-1`, `2001`; profile
mutation; input non-tuple, empty, 129 texts, invalid strings, and 2,001
characters; output non-tuple, wrong count, non-tuple vector, wrong dimension,
integer/bool, NaN/Inf/-Inf, and zero vector. Assert fixed messages, no adapter
call for invalid input, no input leak, and suppressed translated context.

- [ ] **Step 2: Run RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/model_gateway/test_embedding.py::test_gateway_uses_explicit_profile_and_returns_exact_vectors tests/unit/model_gateway/test_embedding.py::test_profile_dimension_is_configuration_controlled -v
```

Expected: collection fails because the model-gateway and fake modules are absent.

- [ ] **Step 3: Implement minimum service contract**

Use these public shapes:

```python
MAX_EMBEDDING_MODEL_ID_CHARS = 128
MAX_EMBEDDING_DIMENSION = 2000
MAX_EMBEDDING_BATCH_SIZE = 128
MAX_EMBEDDING_TEXT_CHARS = 2000


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingProfile:
    model_id: str
    dimension: int


class EmbeddingAdapterError(RuntimeError): ...
class EmbeddingValidationError(ValueError): ...
class EmbeddingUnavailableError(RuntimeError): ...


class EmbeddingPort(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...
```

`EmbeddingGateway` exposes the exact profile and `embed()`. Use exact type
checks, `math.isfinite`, and non-zero sum of squares. Catch only
`EmbeddingAdapterError`. Invalid callers raise exactly `invalid embedding
request`; typed adapter failures or invalid output raise exactly `embedding
unavailable` from None. Never resize or normalize.

- [ ] **Step 4: Implement deterministic fake**

`FakeEmbeddingAdapter(profile, vectors)` copies the mapping, exposes the exact
profile, records each input tuple, and returns mapped vectors in order. Missing
text raises `EmbeddingAdapterError("embedding adapter failed")` from None. It
must not import network, filesystem, environment, random, model SDK, retrieval,
or database modules.

- [ ] **Step 5: Add architecture guards and confirm GREEN**

Walk the complete AST. Gateway imports may use only exact standard-library
symbols; fake imports may use only `collections.abc` and exact embedding names.
Reject nested, relative, alias, wildcard, SQL, network, SDK, environment,
filesystem, retrieval, and database imports.

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/model_gateway/test_embedding.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check services/model_gateway adapters/embedding tests/unit/model_gateway
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy services/model_gateway adapters/embedding tests/unit/model_gateway
```

- [ ] **Step 6: Commit Task 1**

```bash
git add services/model_gateway adapters/embedding tests/unit/model_gateway
git commit -m "feat: define deterministic embedding boundary"
```

---

### Task 2: Add deterministic pgvector schema and insert-only persistence

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.lock`
- Modify: `requirements-dev.lock`
- Modify: `infra/postgres/document_models.py`
- Create: `infra/postgres/embedding_repository.py`
- Create: `infra/postgres/migrations/versions/20260820_0005_add_vector_retrieval.py`
- Modify: `infra/postgres/__init__.py`
- Create: `tests/integration/retrieval/test_vector_storage.py`
- Modify: `tests/integration/test_document_versions.py`
- Modify: `tests/integration/test_domain_repository.py`
- Modify: `tests/integration/test_entity_alias_repository.py`

**Interfaces:**
- Consumes: Task 1 `EmbeddingProfile`, Task 009 `DocumentChunkModel`, caller-owned `Session`.
- Produces: `DocumentChunkEmbeddingModel`, `PostgresEmbeddingRepository`, `EmbeddingPersistenceError`, Alembic head `20260820_0005`.

- [ ] **Step 1: Add and install pgvector dependency**

Add `"pgvector>=0.4,<0.6"` and exact `pgvector==0.5.0` lock entries. Do not add
NumPy. Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip install "pgvector==0.5.0"
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
```

- [ ] **Step 2: Write schema and repository RED tests**

Create future imports and assert:

```python
def test_vector_metadata_declares_exact_profile_table_and_indexes() -> None:
    table = DocumentChunkEmbeddingModel.__table__
    assert set(table.primary_key.columns.keys()) == {"chunk_id", "embedding_model"}
    assert str(table.c.embedding.type).upper() == "VECTOR(8)"
    assert {index.name for index in table.indexes} >= {
        "ix_document_chunk_embeddings_model",
        "ix_document_chunk_embeddings_hnsw_cosine",
    }


def test_vector_migration_is_current_head() -> None:
    assert _current_revision() == "20260820_0005"
```

Before production code, add extension/table/columns/PK/FK/checks, HNSW
method/opclass, B-tree index, offline SQL, downgrade/table removal/extension
retention, valid insert, model coexistence, duplicate, missing chunk, wrong
dimension, zero vector, caller transaction, fixed error, and recovery tests.

- [ ] **Step 3: Run storage RED**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval/test_vector_storage.py -v
```

Expected: collection fails because model, repository, and migration are absent.

- [ ] **Step 4: Implement aligned metadata and migration**

Define `DATABASE_EMBEDDING_DIMENSION = 8`,
`DATABASE_EMBEDDING_MODEL_ID = "fake-deterministic-v1"`, and
`DocumentChunkEmbeddingModel` with composite primary key, named chunk FK,
`VECTOR(8)`, nonblank model check, non-zero `vector_norm` check, B-tree model
index, and HNSW cosine index. Migration 0005 creates the vector extension,
same table/indexes, and leaves the extension after downgrade. Hard-code 8 in
the revision; never import application constants into migration history.

- [ ] **Step 5: Implement insert-only repository**

```python
class EmbeddingPersistenceError(RuntimeError): ...


class PostgresEmbeddingRepository:
    def __init__(self, session: Session, profile: EmbeddingProfile) -> None: ...
    def insert(self, chunk_id: UUID, embedding: tuple[float, ...]) -> None: ...
```

Reject non-exact/non-8 profiles and invalid UUID/vector before SQL with exactly
`embedding record violates persistence constraints`. Insert inside
`session.begin_nested()`, flush, catch only `IntegrityError`, translate to the
same message from None, and never commit or update.

- [ ] **Step 6: Update exact Alembic-head consumers**

Change only exact head assertions from `20260820_0004` to `20260820_0005` in
the three named existing integration files. Do not widen their guards.

- [ ] **Step 7: Confirm storage GREEN**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval/test_vector_storage.py tests/integration/test_document_versions.py tests/integration/test_domain_repository.py::test_migration_upgrades_an_empty_postgresql_database tests/integration/test_entity_alias_repository.py::test_alias_migration_is_current_head -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic heads
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic upgrade head --sql
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check infra/postgres tests/integration/retrieval/test_vector_storage.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy infra/postgres tests/integration/retrieval/test_vector_storage.py
```

Expected: zero skips under explicit DB URL; one head `20260820_0005`; offline
SQL includes extension/table/HNSW; Ruff/mypy pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add pyproject.toml requirements.lock requirements-dev.lock infra/postgres tests/integration/retrieval/test_vector_storage.py tests/integration/test_document_versions.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py
git commit -m "feat: persist model-versioned chunk embeddings"
```

---

### Task 3: Extract shared PostgreSQL retrieval security support

**Files:**
- Create: `infra/postgres/retrieval_support.py`
- Modify: `infra/postgres/lexical_retrieval.py`
- Modify: `tests/unit/retrieval/test_lexical_contracts.py`
- Test: `tests/integration/retrieval/test_lexical_acl.py`

**Interfaces:**
- Consumes: Task 013 lexical ACL/filter/excerpt behavior.
- Produces: `authorized_document_constraints(scope, filters)` and `evidence_excerpt(text, query)` for lexical and vector adapters.

- [ ] **Step 1: Write shared-helper structure RED tests**

Add future imports and direct tests:

```python
def test_shared_retrieval_support_canonicalizes_scope_ids_fail_closed() -> None:
    scope = AuthorizationScope(
        allowed_ship_ids={VALID_UUID, VALID_UUID.upper(), "not-a-uuid", BRACED_UUID}
    )
    _predicates, parameters = authorized_document_constraints(
        scope, KnowledgeFilters()
    )
    assert parameters["scope_ship_ids"] == (UUID(VALID_UUID),)


def test_shared_excerpt_preserves_unicode_fold_offsets() -> None:
    text = "ß" * 1500 + "NEEDLE" + "x" * 2494
    excerpt = evidence_excerpt(text, "NEEDLE")
    assert len(excerpt) == 2000
    assert "NEEDLE" in excerpt
```

Add a complete-AST guard allowing only standard library, SQLAlchemy
expressions, exact document models, and exact contract names. Reject nested,
relative, alias, wildcard, parser, API, Wiki, Agent, SDK, and business imports.

- [ ] **Step 2: Run helper RED**

Run the two new nodes. Expected: collection fails because
`infra.postgres.retrieval_support` does not exist.

- [ ] **Step 3: Extract helpers without changing lexical behavior**

Move canonical UUID parsing, the four ACL predicates/parameters, optional
document/ship/project filters, Unicode casefold span, and 2,000-character
excerpt. Use exact signatures:

```python
def authorized_document_constraints(
    user_scope: AuthorizationScope,
    filters: KnowledgeFilters,
) -> tuple[tuple[ColumnElement[bool], ...], dict[str, object]]: ...


def evidence_excerpt(text_value: str, query: str) -> str: ...
```

Update lexical retrieval to merge helper parameters with query/pattern/limit.
Preserve one SELECT, score, order, wildcard binding, timeout, error, and
evidence behavior exactly.

- [ ] **Step 4: Confirm helper and full lexical GREEN**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/retrieval/test_lexical_contracts.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval/test_lexical_acl.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check infra/postgres/retrieval_support.py infra/postgres/lexical_retrieval.py tests/unit/retrieval/test_lexical_contracts.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy infra/postgres/retrieval_support.py infra/postgres/lexical_retrieval.py tests/unit/retrieval/test_lexical_contracts.py
```

Expected: all Task 013 lexical tests remain green with unchanged SQL/evidence.

- [ ] **Step 5: Commit Task 3**

```bash
git add infra/postgres/retrieval_support.py infra/postgres/lexical_retrieval.py tests/unit/retrieval/test_lexical_contracts.py
git commit -m "refactor: share PostgreSQL retrieval authorization"
```

---

### Task 4: Implement vector service orchestration and PostgreSQL search

**Files:**
- Create: `services/retrieval/vector.py`
- Modify: `services/retrieval/__init__.py`
- Create: `infra/postgres/vector_retrieval.py`
- Modify: `infra/postgres/__init__.py`
- Create: `tests/unit/retrieval/test_vector_contracts.py`
- Create: `tests/integration/retrieval/test_vector_acl.py`

**Interfaces:**
- Consumes: Task 1 gateway/profile; Task 2 embedding table; Task 3 support; existing authorization, filters, evidence.
- Produces: `VectorSearchPort`, `VectorRetriever`, `VectorRetrievalValidationError`, `VectorRetrievalError`, `PostgresVectorSearchAdapter`.

- [ ] **Step 1: Write vector service RED cases**

Create a recording port and primary test:

```python
def test_vector_retriever_embeds_once_and_delegates_trusted_scope() -> None:
    profile = EmbeddingProfile(model_id="fake-deterministic-v1", dimension=8)
    query_vector = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    fake = FakeEmbeddingAdapter(profile, {"ballast pump": query_vector})
    gateway = EmbeddingGateway(fake)
    port = RecordingVectorPort([_evidence(vector_score=0.95)])
    scope = _scope()
    filters = KnowledgeFilters()

    result = VectorRetriever(gateway, port).retrieve(
        "  ballast pump  ", scope, filters, limit=7
    )

    assert result == [_evidence(vector_score=0.95)]
    assert fake.calls == (("ballast pump",),)
    assert port.calls == [
        ("ballast pump", query_vector, profile, scope, filters, 7)
    ]
```

Prewrite invalid exact-type/blank/NUL/1,001-character query, scope/filter
subclass, boolean/non-integer/out-of-range limit, fixed error/no-value,
no-embed/no-search, typed embedding failure translation, and AST guard cases.

- [ ] **Step 2: Run service RED**

Run the primary node. Expected: collection fails because vector service is absent.

- [ ] **Step 3: Implement minimum vector service**

```python
class VectorRetrievalValidationError(ValueError): ...
class VectorRetrievalError(RuntimeError): ...


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
```

`VectorRetriever` validates exact types, strips once, embeds one query in one
gateway call, translates only `EmbeddingUnavailableError` to
`VectorRetrievalError("vector retrieval unavailable")` from None, and calls
the search port once. Export vector names without removing lexical exports.

- [ ] **Step 4: Write complete PostgreSQL retrieval RED matrix**

Use `PostgresDocumentRepository` and `PostgresEmbeddingRepository` for
synthetic fixtures. Prewrite the primary two-project test before the adapter:

```python
def test_vector_search_returns_only_the_authorized_project(
    migrated_engine: Engine,
) -> None:
    allowed_project = UUID("b2000000-0000-0000-0000-000000000001")
    denied_project = UUID("b2000000-0000-0000-0000-000000000002")
    allowed_chunk, denied_chunk = _persist_two_project_vector_fixture(
        migrated_engine,
        allowed_project=allowed_project,
        denied_project=denied_project,
        embedding=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    result = _retrieve(
        migrated_engine,
        query="ballast pump",
        query_vector=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        scope=_project_scope(allowed_project),
    )
    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}
    assert result[0].vector_score == result[0].retrieval_score
```

Also prewrite model isolation, document/ship/project filters, out-of-scope
filters, limit 1, an independent cosine score oracle, newer-time/UUID tie
order, exact evidence, literal and semantic-only excerpts, SQL profile/ACL/
order/limit, read-only transaction, local timeout, and exact-one-query tests.

- [ ] **Step 5: Run primary PostgreSQL RED**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval/test_vector_acl.py::test_vector_search_returns_only_the_authorized_project -v
```

Expected: collection fails because `PostgresVectorSearchAdapter` is absent.

- [ ] **Step 6: Implement minimum PostgreSQL adapter**

```python
class PostgresVectorSearchAdapter(VectorSearchPort):
    def __init__(self, engine: Engine, profile: EmbeddingProfile) -> None: ...
```

Reject non-exact/non-8 profile before SQL with only `vector retrieval
unavailable`. Join embedding, chunk, version, document; compute
`embedding.cosine_distance(bindparam("query_embedding"))`; filter exact model
plus shared constraints; order distance ascending, source time descending,
chunk UUID ascending; bind limit. Execute in a private read-only transaction
with transaction-local 2,000 ms timeout.

Set `score = max(0.0, 1.0 - float(distance))`; reject non-finite distance with
the fixed error. Build exact evidence with retrieval/vector score equal,
lexical/rerank unset, and shared excerpt. Translate only `SQLAlchemyError`
from None.

- [ ] **Step 7: Confirm full Task 4 GREEN**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/retrieval/test_vector_contracts.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval/test_vector_acl.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check services/retrieval infra/postgres/vector_retrieval.py tests/unit/retrieval tests/integration/retrieval/test_vector_acl.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy services/retrieval infra/postgres/vector_retrieval.py tests/unit/retrieval tests/integration/retrieval/test_vector_acl.py
```

Add exact complete-AST guards for vector service/adapter before final run;
reject SDK, parser, API, Wiki, Agent, hybrid, reranker, and business imports.

- [ ] **Step 8: Commit Task 4**

```bash
git add services/retrieval infra/postgres/vector_retrieval.py infra/postgres/__init__.py tests/unit/retrieval tests/integration/retrieval/test_vector_acl.py
git commit -m "feat: retrieve authorized chunks by vector"
```

---

### Task 5: Complete security characterization, docs, and Task 014 gates

**Files:**
- Modify: `tests/integration/retrieval/test_vector_acl.py`
- Modify: `tests/unit/model_gateway/test_embedding.py`
- Modify: `tests/unit/retrieval/test_vector_contracts.py`
- Modify only after genuine RED: Task 1-4 production files
- Modify: `docs/03-knowledge-system.md`
- Modify: `docs/06-security.md`

**Interfaces:**
- Consumes: completed Task 014 embedding, storage, and retrieval.
- Produces: security-complete vector retrieval ready for Task 015 without implementing it.

- [ ] **Step 1: Add full ACL and global-null characterization**

Parameterize one equally similar chunk denied independently by:

```text
CONFIDENTIAL document / INTERNAL scope
quality department / engineering scope
ship B / only ship A allowed
project B / only project A allowed
```

Add three-dimensional intersection cases where exactly one of department,
ship, or project differs. Add a fully global PUBLIC vector document and prove
an empty default scope retrieves it but no scoped document. Run before any
production change. These are expected GREEN if Task 4 is correct; never
manufacture a RED state.

- [ ] **Step 2: Add malformed scope, filter, and model no-bypass coverage**

Use canonical UUIDs mixed with `not-a-uuid`, brace-wrapped UUID, and `1`.
Assert invalid values neither raise nor grant; uppercase canonical UUID is
accepted. Assert out-of-scope ship/project filters return zero after exactly
one candidate SELECT. Assert another model's closer vector is absent.

- [ ] **Step 3: Add SQL injection, read-only, failure, and pool coverage**

Use `x'); DROP TABLE documents; --` as malicious query/model text and a
synthetic literal-bearing document. Capture SQL and binds. Assert values are
absent from SQL text and present in parameters, unrelated rows do not appear,
one candidate SELECT executes, no DML/DDL occurs, source/embedding row counts
are unchanged, and all tables remain queryable.

Point a temporary engine at a guaranteed unavailable local port. Assert
exactly `vector retrieval unavailable`, no secret query/vector/model, no
cause, and suppressed context. Prove successful and failed searches return
the engine pool to zero checked-out connections.

- [ ] **Step 4: Apply only test-proven minimal hardening**

If a new characterization genuinely fails, record that RED, make the smallest
production change, rerun the exact node, then the focused suite. Do not add
hybrid or reranking abstractions.

- [ ] **Step 5: Document the boundary**

Update `docs/03-knowledge-system.md` with embedding profile/provenance,
storage, fake/port boundary, cosine score/order, model isolation, vector
evidence, all-version behavior, no automatic embedding job, filtered-HNSW
recall limitation, and Task 015 exclusion.

Update `docs/06-security.md` with vector ACL-before-order/limit, bound vectors
and model IDs, read-only/2,000 ms/20-row behavior, fixed errors, embeddings as
derived data, retrieved text as untrusted, and no model-supplied identity.

- [ ] **Step 6: Run focused and adjacent suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/model_gateway tests/unit/retrieval tests/unit/domain/test_documents.py tests/unit/ingestion/test_document_store.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/retrieval tests/integration/test_document_versions.py tests/security -v
```

Expected: zero failures and zero skips in explicit database paths.

- [ ] **Step 7: Run complete acceptance and scope gates**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m alembic heads
git diff --check 080f2f1...HEAD
git diff --name-only 080f2f1...HEAD
```

Expected: all tests/Ruff/mypy/pip pass; one head is `20260820_0005`; scope
contains only approved spec/plan, embedding/vector dependency, service,
adapter, PostgreSQL, tests, and two docs. No Task 015 or forbidden subsystem
file appears.

- [ ] **Step 8: Commit and stop before Task 015**

```bash
git add tests/unit/model_gateway tests/unit/retrieval tests/integration/retrieval/test_vector_acl.py docs/03-knowledge-system.md docs/06-security.md
git commit -m "test: harden vector retrieval authorization"
```

Record exact commands/results, files, decisions, acceptance, and limitations.
Request independent read-only spec/code/security review of `080f2f1...HEAD`.
Resolve verified P0/P1/P2 through focused TDD and rerun the complete gate after
material fixes. Report P3 limitations. Do not merge, push, or begin Task 015
without explicit user choice.
