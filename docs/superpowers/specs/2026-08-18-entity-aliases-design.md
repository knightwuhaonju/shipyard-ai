# Task 007 Entity Aliases and Canonicalization Design

## 1. Purpose and scope

Task 007 adds deterministic, explicit alias links for the three V1 canonical
entity types that need name/code normalization first:

- `Supplier`
- `Equipment`
- `Material`

The feature lets multiple explicitly registered strings resolve to one
canonical UUID without changing the canonical entity, replacing its source
identity, or making an automatic fuzzy merge. It does not add Task 008
fixtures, an API endpoint, an Agent tool, an approval UI, or a fuzzy-matching
engine.

## 2. Architecture boundaries

- `packages.domain` owns the immutable alias value and normalization rules. It
  uses only the Python standard library and domain-local validation types.
- `infra.postgres` owns SQLAlchemy persistence, exact indexed lookup, safe
  integrity translation, and Alembic migration `20260818_0002`.
- `services.entity_resolution` owns authorization and resolution policy. It
  depends on domain types and structural protocols/callables, not SQLAlchemy.
- Authentication remains separate from authorization. The service receives a
  server-created `UserContext` and derives `AuthorizationScope` with the
  existing authorization service.
- The Agent, UI, and model never receive database credentials and gain no
  alias-write capability in this task.

Dependency direction remains:

```text
service -> domain/contracts
infra -> domain
apps (future wiring) -> service + infra
```

The domain package does not import the service or infrastructure packages.

## 3. Domain model

### 3.1 Supported entity types

`AliasEntityType` is a string enum with exactly:

- `SUPPLIER = "supplier"`
- `EQUIPMENT = "equipment"`
- `MATERIAL = "material"`

No generic arbitrary entity-type string is accepted. Adding another type
requires an explicit domain, migration, repository, authorization, and test
change.

### 3.2 EntityAlias

`EntityAlias` is a frozen, slotted, keyword-only dataclass with:

- `id: UUID`
- `entity_type: AliasEntityType`
- `entity_id: UUID`
- `alias: str`
- `source_system: str | None = None`
- `normalized_alias: str` computed during construction and not accepted as an
  independent caller value

Validation requires UUID identifiers, non-blank alias text, and a non-blank
`source_system` when one is present. Computing `normalized_alias` from `alias`
prevents callers from persisting a mismatched search key.

Alias records are organizational mappings rather than replicas of live
business records, so they follow the approved alias model's optional
`source_system` instead of inventing `source_id` or `source_updated_at` fields.
The linked canonical entity retains its own complete source provenance.

## 4. Deterministic normalization

`normalize_alias(value: str) -> str` performs only:

1. type and non-blank validation;
2. Unicode NFKC normalization;
3. Unicode `casefold` for case-insensitive comparison;
4. leading/trailing whitespace removal; and
5. collapse of each internal whitespace run to one ASCII space.

It deliberately does not:

- strip accents or combining marks;
- remove punctuation;
- transliterate between scripts;
- perform edit-distance, phonetic, embedding, or model-based similarity; or
- rewrite a known brand spelling.

Consequently `Wärtsilä`, `Wartsila`, and `瓦锡兰` have three distinct
normalized keys and must be registered explicitly. Case and compatibility
width variants of the same written alias share a key. A misspelling such as
`Wartsilla` returns no result until a human-authorized workflow explicitly
adds it.

Normalization behavior is a durable storage contract. Changing it later
requires a migration that recomputes stored normalized keys and resolves any
new collisions before deployment.

## 5. PostgreSQL persistence

### 5.1 Table shape

One `entity_aliases` table stores:

- `id UUID PRIMARY KEY`
- `entity_type TEXT NOT NULL`
- `alias TEXT NOT NULL`
- `normalized_alias TEXT NOT NULL`
- `source_system TEXT NULL`
- `supplier_id UUID NULL REFERENCES suppliers(id)`
- `equipment_id UUID NULL REFERENCES equipment(id)`
- `material_id UUID NULL REFERENCES materials(id)`

The table has named checks for:

- non-blank `alias` and `normalized_alias`;
- non-blank `source_system` when present; and
- exact alignment between `entity_type` and one, and only one, populated
  canonical foreign-key column.

This slightly wider persistence shape preserves the domain's uniform
`entity_type + entity_id` interface while giving PostgreSQL real foreign keys.
All foreign keys use default `NO ACTION`; no cascade is introduced.

### 5.2 Lookup uniqueness

Two partial unique indexes define collision behavior:

- global: `(entity_type, normalized_alias)` where `source_system IS NULL`;
- source-specific: `(entity_type, source_system, normalized_alias)` where
  `source_system IS NOT NULL`.

The same normalized alias may exist for different entity types. Within one
entity type and lookup scope, it can point to only one canonical entity. A
conflicting reassignment fails safely; Task 007 provides no update, delete,
merge, or upsert operation.

Indexes are also created for the three canonical foreign-key columns.

### 5.3 Migration

Alembic revision `20260818_0002` has `20260817_0001` as its sole parent. It
creates only `entity_aliases`, its constraints, and indexes. Downgrade removes
only this table and its indexes. Existing empty-database migration tests are
updated to expect head `20260818_0002` without weakening the protected exact
`shipyard_ai_test` downgrade guard.

## 6. Repository contract

`AliasRepository` receives a caller-owned SQLAlchemy `Session` and exposes:

```python
def insert(self, alias: EntityAlias) -> None: ...

def resolve(
    self,
    entity_type: AliasEntityType,
    raw_alias: str,
    source_system: str | None = None,
) -> EntityAlias | None: ...
```

`insert` maps `entity_type/entity_id` to the corresponding typed FK, uses a
nested savepoint plus `flush`, and never commits. Unique, FK, and CHECK
violations become `AliasPersistenceError` with fixed text that includes no
alias value, SQL, or credentials.

`resolve` normalizes `raw_alias` deterministically and performs parameterized
SQLAlchemy queries:

- with `source_system`: query that exact source-specific scope first, then the
  global `NULL` scope;
- without `source_system`: query only the global scope.

It never performs substring, wildcard, edit-distance, phonetic, vector, or LLM
matching. No listing/search-all method is added.

## 7. Service and authorization policy

`EntityResolutionService` depends on an alias-reader protocol and an injected
`equipment_by_id: Callable[[UUID], Equipment | None]`. It does not import the
PostgreSQL repository.

Its public operation is:

```python
def resolve(
    self,
    *,
    entity_type: AliasEntityType,
    raw_alias: str,
    user_context: UserContext,
    source_system: str | None = None,
    requested_scope: AuthorizationScope | None = None,
) -> EntityAlias | None: ...
```

The service derives the trusted scope with
`authorization_scope_for(user_context, requested_scope)`.

Authorization policy:

- Supplier and Material aliases are global master data. A valid server-created
  `UserContext` may resolve them.
- Equipment aliases are ship-scoped. After exact alias lookup, the service
  loads the canonical `Equipment` through the injected read function and
  returns the alias only when `str(equipment.ship_id)` is present in
  `scope.allowed_ship_ids`.
- Missing aliases, missing equipment, and unauthorized equipment all return
  `None`. This prevents lookup results from revealing whether an out-of-scope
  entity exists.
- The service never trusts a user ID or authorization scope supplied by model
  output. Future application wiring must obtain `UserContext` from the trusted
  authentication adapter.

No alias-write service is exposed. Explicit mappings are inserted only through
the repository in a caller-owned administrative/import transaction until a
later human-authorized workflow is designed.

## 8. Failure behavior

- Invalid domain input raises the existing `DomainValidationError` with fixed,
  value-free messages.
- Persistence constraint failures raise `AliasPersistenceError` with fixed,
  value-free text and suppressed database exception chaining.
- Exact lookup returns `None` for absent or unauthorized results.
- A malformed/unsupported entity type cannot reach persistence or lookup
  because the domain enum is closed.
- A collision is preserved as an error; it is never silently reassigned or
  merged.

## 9. Testing strategy

### Unit tests

- `Wärtsilä`, `Wartsila`, and `瓦锡兰` retain three distinct normalized keys.
- case, compatibility-width, and whitespace variants normalize
  deterministically.
- blank aliases and blank optional source systems fail without echoing values.
- the frozen alias computes its own normalized key.
- source-specific lookup takes precedence over global lookup; source omission
  cannot see source-specific rows.
- `Wartsilla` returns `None` and creates no mapping.
- Supplier/Material resolution works for a valid authenticated context.
- Equipment resolution succeeds for an allowed ship and returns `None` for a
  different ship, empty scope, or missing equipment.
- requested scopes can narrow but never widen equipment visibility.

Unit tests use deterministic fakes and make no network, database, or external
model call.

### PostgreSQL integration tests

- migration chain upgrades from base to `20260818_0002` and has no metadata
  drift;
- the three explicit Wärtsilä/Wartsila/瓦锡兰 rows point to one synthetic
  Supplier UUID and all resolve exactly;
- global and source-specific uniqueness/collision behavior executes in
  PostgreSQL;
- each supported entity type round-trips through its typed FK;
- dangling targets and target/type mismatches are rejected;
- source-specific resolution falls back to global and never crosses to a
  different source;
- repository failures leave the caller-owned Session usable;
- errors do not contain the rejected alias or credentials.

All PostgreSQL tests use synthetic data and only the existing guarded
`TEST_DATABASE_URL` flow.

### Security tests

- an Equipment alias linked to ship A is not returned to a context limited to
  ship B;
- an empty scope cannot resolve Equipment aliases;
- absence and authorization denial are observationally identical (`None`).

### Final gate

- focused RED then GREEN evidence for each behavior slice;
- relevant unit, integration, and security suites;
- full pytest suite;
- Ruff;
- mypy;
- Alembic offline SQL and metadata drift check;
- installed-artifact/Docker deployment smoke; and
- diff hygiene against the branch base.

## 10. Expected files

Create:

- `packages/domain/aliases.py`
- `infra/postgres/alias_repository.py`
- `infra/postgres/migrations/versions/20260818_0002_create_entity_aliases.py`
- `services/entity_resolution/__init__.py`
- `services/entity_resolution/service.py`
- `tests/unit/test_entity_aliases.py`
- `tests/integration/test_entity_alias_repository.py`
- `tests/security/test_entity_alias_scope.py`

Modify:

- `packages/domain/__init__.py`
- `infra/postgres/models.py`
- `infra/postgres/__init__.py`
- `tests/integration/test_domain_repository.py`
- `tests/integration/test_deployment.py` if installed public imports expand
- `infra/postgres/README.md`

No Task 008 file or synthetic-fixture package is created.

## 11. Acceptance mapping

- `Wärtsilä`, `Wartsila`, and `瓦锡兰` resolve through three explicit alias
  rows to one synthetic canonical Supplier.
- No fuzzy candidate is generated or automatically merged; unregistered
  near-spellings return `None`.
- Alias lookup is scope-safe: global Supplier/Material policy is explicit, and
  Equipment is filtered by server-derived allowed ship scope with no existence
  leak.
- Canonical UUIDs remain internal IDs and never become source-system IDs.
- Public contracts, migration, integration behavior, and operator notes are
  documented and verified.
