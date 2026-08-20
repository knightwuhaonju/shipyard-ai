# Task 013 Lexical Retrieval Design

**Date:** 2026-08-20
**Status:** Approved for implementation planning
**Task:** 013 — ACL-filtered PostgreSQL lexical retrieval

## 1. Purpose

Task 013 adds the first retrieval implementation over immutable normalized
document chunks. It returns traceable `KnowledgeEvidence` records and applies
authorization, caller filters, ranking, deterministic ordering, and the row
limit inside one PostgreSQL candidate query.

The implementation is suitable for mixed Chinese and English V1 content. It
combines PostgreSQL `simple` full-text search with `pg_trgm` literal substring
matching. It does not add embeddings, vector retrieval, hybrid merging,
reranking, an API, a tool, or answer synthesis.

## 2. Non-goals

Task 013 does not:

- implement Task 014 vector storage or embedding adapters;
- implement Task 015 hybrid retrieval or reranking;
- add a knowledge API, Agent behavior, Wiki search, or audit runtime;
- query live ERP, MES, PLM, or another business source;
- infer authorization from model-generated arguments;
- use external search services, models, tokenizers, or language-specific NLP
  libraries;
- mutate document content or business data; or
- select a current document version when several immutable versions coexist.

## 3. Architecture and dependency direction

The dependency flow is:

```text
caller
  -> LexicalRetriever                       # services/retrieval
       -> LexicalSearchPort                 # service-owned port
            -> PostgresLexicalSearchAdapter # infra/postgres
                 -> PostgreSQL document/version/chunk tables
```

`packages.common` owns the shared `DocumentType` enum. The immutable domain
`DocumentVersion` and the transport-independent evidence/filter contracts use
that enum without importing ingestion or infrastructure packages.

`services.retrieval` may depend on `packages.contracts` and standard-library
interfaces. It must not import SQLAlchemy, PostgreSQL models, parser adapters,
model SDKs, FastAPI, the Agent, Wiki, or business-source adapters.

`infra.postgres` implements the search port using SQLAlchemy and PostgreSQL.
Database credentials remain in application configuration and never cross the
service port.

## 4. Document type metadata

Task 013 makes document type explicit and queryable rather than inferring it
from `source_uri` at search time.

```python
class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    TXT = "txt"
    MARKDOWN = "markdown"
```

`DocumentVersion.document_type` is required immutable metadata because a
specific immutable version represents a specific source artifact. The value is
stored in `document_versions.document_type`, protected by a database check
constraint, and indexed for filters.

The migration backfills pre-Task-013 rows only when a known suffix can be
unambiguously derived from the existing `source_uri`, ignoring URI query and
fragment suffixes and treating both `.md` and `.markdown` as `markdown`. If any
existing row cannot be mapped to one of the five approved types, the migration
fails rather than silently inventing metadata. New writes never infer the value
from the URI; callers must supply `DocumentType` explicitly.

## 5. Public contracts

`packages.contracts.evidence` provides frozen Pydantic contracts with unknown
fields forbidden.

```python
class KnowledgeFilters(FrozenContract):
    document_type: DocumentType | None = None
    ship_id: UUID | None = None
    project_id: UUID | None = None


class KnowledgeEvidence(FrozenContract):
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: str
    section: str | None = None
    page: int | None = None
    source_uri: str
    excerpt: str
    retrieval_score: float
    lexical_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None
```

Required text is non-blank and contains no NUL. `page`, when present, is a
positive exact integer. Scores are finite and non-negative. A lexical result
sets both `retrieval_score` and `lexical_score` to the combined lexical score;
future retrieval Tasks may update the general retrieval score and populate
the other optional scores.

The retrieval service exposes:

```python
class LexicalSearchPort(Protocol):
    def search(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]: ...


class LexicalRetriever:
    def __init__(self, port: LexicalSearchPort) -> None: ...

    def retrieve(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int = 10,
    ) -> list[KnowledgeEvidence]: ...
```

`query` must be an exact string whose stripped value is non-empty, NUL-free,
and no longer than 1,000 Unicode code points. `limit` must be an exact integer
from 1 through 20. Invalid input raises a fixed, value-free
`RetrievalValidationError`. The service passes the trusted
`AuthorizationScope` separately from caller filters and never constructs
identity from an untyped mapping.

## 6. Authorization semantics

Authorization is part of the database candidate predicate, before ranking,
ordering, and `LIMIT`:

```text
version.security_level <= scope.security_level
AND (version.department IS NULL OR version.department IN scope.departments)
AND (version.ship_id IS NULL OR version.ship_id IN scope.allowed_ship_ids)
AND (version.project_id IS NULL OR version.project_id IN scope.allowed_project_ids)
```

Null metadata means the document is global for that dimension. Non-null
metadata is scoped and requires exact membership. If several scoped dimensions
are present, all must pass. An empty set therefore grants no resource bound to
that dimension, while a public document unbound on every dimension remains
available at `PUBLIC` clearance.

Authorization-scope ship and project identifiers are strings because the
shared auth contract serves several subsystems. The PostgreSQL adapter accepts
only canonical UUID text when building its bind values. Invalid identifiers
are ignored and never broaden access.

Optional caller filters are additional predicates:

- `document_type` equals the stored version type;
- `ship_id` equals the stored ship ID; and
- `project_id` equals the stored project ID.

A requested ship/project outside the authorization scope naturally returns no
rows because both the filter and the ACL predicate remain in the same query.
There is no post-query authorization filter and no privileged fallback path.

## 7. PostgreSQL indexing and migration

The Task 013 migration:

1. enables the standard `pg_trgm` extension if absent;
2. adds and safely backfills `document_versions.document_type`;
3. makes the column non-null and adds its exact-value check constraint;
4. adds a B-tree document-type index;
5. adds a GIN expression index over
   `to_tsvector('simple', document_chunks.normalized_text)`; and
6. adds a GIN `gin_trgm_ops` index over `normalized_text`.

The full-text expression in the query must match the indexed expression. The
migration does not add a stored engine-specific search value to domain
contracts. Downgrade removes Task 013 columns, constraints, and indexes. It
does not drop `pg_trgm`, because an extension may be shared by another database
object after upgrade.

SQLAlchemy metadata and Alembic must remain aligned, and Task 013 leaves one
Alembic head.

## 8. Candidate query and ranking

The adapter treats the raw query as data, never SQL syntax. It uses bind
parameters and `plainto_tsquery('simple', query)`. Literal substring matching
escapes `%`, `_`, and the escape character before using `ILIKE`, so caller text
cannot introduce wildcard semantics.

A chunk matches when either:

- its `simple` text vector matches the plain text query; or
- its normalized text contains the exact query case-insensitively.

The explicit lexical score is:

```text
0.7 * ts_rank_cd(simple_vector, plain_query, normalization=32)
+ 0.3 * similarity(normalized_text, query)
```

This gives word-aware ranking for English, identifiers, and whitespace-tokenized
content while retaining Chinese and partial literal recall through trigram
similarity. The predicate, score, ACL, metadata filters, ordering, and limit are
one SELECT over joined `documents`, `document_versions`, and
`document_chunks`.

Results order by:

1. combined score descending;
2. `source_updated_at` descending;
3. `chunk_id` ascending.

The final UUID tie-break makes repeated queries deterministic. Task 013
searches every authorized immutable version because no current-version marker
or lifecycle exists yet.

## 9. Evidence assembly and errors

The adapter constructs evidence only from rows already authorized by the SQL
predicate. It never returns ORM records or ACL metadata to callers.

`excerpt` is a deterministic at-most-2,000-code-point window around the first
literal case-insensitive query occurrence. If the lexical match came only from
full-text token matching, the excerpt starts at the beginning of the chunk.
The original normalized text remains stored unchanged; excerpt construction is
presentation of authorized source content, not a new source of truth.

The PostgreSQL adapter opens its own short-lived session and transaction,
marks it read-only, applies a transaction-local 2,000 ms statement timeout,
executes the bounded SELECT, and closes the session. It never commits business
data and never changes a caller-owned session.

Expected SQLAlchemy/database failures become a fixed
`LexicalRetrievalError("lexical retrieval unavailable")` without SQL text,
query text, credentials, document content, or driver details. Contract
validation failures remain `RetrievalValidationError`. No error message
contains the query or scope values.

## 10. Security and source-of-truth behavior

- Original documents and immutable versions remain authoritative.
- Evidence is a pointer and excerpt from authorized document content, not a
  model conclusion or execution instruction.
- Retrieved content remains untrusted and cannot influence SQL, authorization,
  tool identity, or runtime control flow.
- The service receives a server-derived `AuthorizationScope` separately from
  model/caller filters.
- Queries are parameterized, read-only, timeout-bounded, and row-bounded.
- No real customer data, production database, credentials, external model, or
  network service is used in tests.

## 11. Test strategy

Every behavior change follows RED, expected failure, minimal GREEN, focused
test, relevant suite, Ruff, and mypy.

Contract/unit coverage verifies:

- exact immutable `DocumentType`, filters, and evidence values;
- score, text, page, query, and limit validation;
- port/service delegation without SQLAlchemy imports;
- safe fixed error messages;
- literal wildcard escaping and bounded excerpt behavior; and
- architecture/import boundaries.

Migration and PostgreSQL integration coverage verifies:

- `pg_trgm`, the document-type column/constraint, and all three indexes;
- metadata/current-head/offline-SQL consistency;
- English, Chinese, identifier, and literal wildcard matching;
- deterministic scoring/order and limit behavior;
- document type, ship, and project filters;
- global documents and each department/ship/project/security ACL dimension;
- multiple simultaneous scope dimensions require intersection;
- invalid UUID values in trusted scope never broaden access;
- a requested out-of-scope ship/project returns zero results;
- cross-project retrieval returns zero leaked chunks; and
- captured SQL contains ACL predicates and `LIMIT`, demonstrating that
  authorization is in the database query path rather than post-filtered.

All fixtures are synthetic. Integration tests target only the protected
`shipyard_ai_test` database.

## 12. Expected files

Create:

- `packages/common/document_types.py`
- `packages/contracts/evidence.py`
- `services/retrieval/__init__.py`
- `services/retrieval/lexical.py`
- `infra/postgres/lexical_retrieval.py`
- `infra/postgres/migrations/versions/20260820_0004_add_lexical_retrieval.py`
- `tests/unit/retrieval/__init__.py`
- `tests/unit/retrieval/test_lexical_contracts.py`
- `tests/integration/retrieval/__init__.py`
- `tests/integration/retrieval/test_lexical_acl.py`

Modify:

- `packages/common/__init__.py`
- `packages/contracts/__init__.py`
- `packages/domain/documents.py`
- `infra/postgres/document_models.py`
- `infra/postgres/document_repository.py`
- `infra/postgres/__init__.py`
- existing document domain, store, and persistence tests that construct or
  inspect `DocumentVersion`
- `docs/03-knowledge-system.md`
- `docs/06-security.md`

No Task 014 vector/embedding file, Task 015 hybrid/reranker file, API, Wiki,
Agent, tool-runtime, parser, chunker, OCR, dependency lock, or business-domain
entity is in scope.

## 13. Acceptance mapping

| Task 013 criterion | Design evidence |
|---|---|
| Authorization filter is applied inside query path | One joined SELECT contains security, department, ship, and project ACL predicates before ordering and `LIMIT`; captured-SQL integration guard |
| Supports document type/ship/project filters | Explicit immutable `DocumentType` on versions and typed optional `KnowledgeFilters` predicates |
| Returns `KnowledgeEvidence` contracts | Frozen public evidence contract populated only from authorized rows |
| Cross-project test returns zero leaked chunks | Synthetic two-project integration fixture and explicit out-of-scope zero-result assertion |

## 14. Known limitations

- Chinese recall is literal/trigram-oriented; Task 013 adds no dedicated CJK
  tokenizer or dictionary.
- Search includes all authorized immutable versions because the schema has no
  current-version lifecycle marker.
- Rank weights are fixed V1 constants; evaluation-driven tuning belongs to a
  later retrieval/evaluation change.
- `pg_trgm` remains installed after downgrade to avoid deleting a potentially
  shared extension.
