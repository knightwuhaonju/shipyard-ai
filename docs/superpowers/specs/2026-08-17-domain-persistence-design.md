# Task 006 Domain Persistence Design

## 1. Scope

Task 006 adds PostgreSQL persistence for the nine Task 005 domain entities:

- Ship
- ShipSystem
- Drawing
- Equipment
- Material
- BOMItem
- Supplier
- PurchaseOrder
- ProjectTask

The task supplies SQLAlchemy 2.x persistence models, a minimal repository,
an Alembic migration, PostgreSQL integration tests, CI database provisioning,
and deployment packaging for the infrastructure modules.

The task does not add aliases, upsert or synchronization policy, updates,
deletes, business-specific queries, source adapters, authorization behavior,
agent access, or any Task 007 behavior.

## 2. Architecture Boundaries

- `packages/domain` remains unchanged and imports no SQLAlchemy, Alembic,
  PostgreSQL driver, FastAPI, or model SDK.
- ORM models and repositories live under `infra/postgres`.
- The Agent never imports or calls the repository. Later services may use
  approved infrastructure through their own interfaces; that is outside this
  task.
- PostgreSQL stores normalized internal copies. It does not write back to ERP,
  MES, PLM, or any other source system.
- Canonical UUIDs remain distinct from source-system identifiers.
- All test data is synthetic.
- Relational foreign keys implement the V1 relationship model. No graph
  database, triggers, or cross-ship relationship rules are introduced.

The migration revision remains in the repository's existing Alembic location,
`infra/postgres/migrations/versions/`, because `alembic.ini` already declares
`infra/postgres/migrations` as its script location. This intentionally differs
from the generic example path in the Task file.

## 3. Persistence Components

### 3.1 SQLAlchemy models

`infra/postgres/models.py` defines one SQLAlchemy Declarative base and nine
separate persistence models. The persistence models do not inherit from the
frozen domain dataclasses. This keeps the dependency direction explicit and
avoids runtime ORM instrumentation of immutable, slotted domain objects.

Table names are:

- `ships`
- `ship_systems`
- `drawings`
- `equipment`
- `materials`
- `bom_items`
- `suppliers`
- `purchase_orders`
- `project_tasks`

All models use SQLAlchemy 2.x `Mapped` annotations and PostgreSQL-compatible
column types.

### 3.2 Repository

`infra/postgres/repositories.py` defines a single `DomainRepository` bound to a
SQLAlchemy `Session`.

Its public behavior is deliberately small:

```python
repository.insert(entity) -> None
repository.get(entity_type, entity_id) -> entity | None
```

`insert` accepts only the nine Task 005 entity types. It converts the immutable
domain object to its corresponding persistence model, opens a savepoint, adds
the row, and flushes it. It does not commit the caller's transaction.

`get` accepts one of the nine entity classes and a canonical UUID. It uses the
matching ORM model, then explicitly rebuilds the immutable domain object. The
generic signature preserves the requested entity type in the return type.

No upsert, update, delete, list, filtering, aggregate loading, or source-system
synchronization behavior is provided.

### 3.3 Conversion boundary

Conversions are explicit and exhaustively registered for the nine entity
types. They preserve:

- canonical UUIDs
- all source fields
- timezone-aware source timestamps
- every optional relationship and optional business field
- exact `Decimal` values wrapped by `PositiveQuantity` or `Progress`
- Python `date` and strict Boolean values

Loading always invokes the Task 005 domain constructors. Persisted data must
therefore satisfy both database constraints and domain validation.

## 4. Relational Schema

### 4.1 Shared columns and constraints

Every table has:

- `id UUID PRIMARY KEY`
- `source_system TEXT NOT NULL`
- `source_id TEXT NOT NULL`
- `source_updated_at TIMESTAMPTZ NOT NULL`
- a unique constraint on `(source_system, source_id)`
- non-blank checks on `source_system` and `source_id`

Required text columns reject blank or whitespace-only values. Optional text
columns permit `NULL` but reject blank or whitespace-only values when present.
Foreign-key columns are indexed. Foreign keys use PostgreSQL's default
`NO ACTION` behavior; this task has no cascade or delete API.

### 4.2 Entity columns

`ships` stores `ship_code`, optional `name`, optional `customer_name`, optional
`vessel_type`, and optional `planned_delivery_date`. `ship_code` is globally
unique and non-blank.

`ship_systems` stores required `ship_id`, `system_code`, and `name`.
`ship_id` references `ships.id`.

`drawings` stores required `ship_id`, optional `system_id`, `drawing_no`,
`title`, `revision`, and optional `status`. The foreign keys reference
`ships.id` and `ship_systems.id`.

`equipment` stores required `ship_id`, optional `system_id`, optional
`drawing_id`, `equipment_code`, optional `manufacturer`, and optional `model`.
The foreign keys reference `ships.id`, `ship_systems.id`, and `drawings.id`.

`materials` stores `material_code`, `description`, optional `specification`,
and optional `unit`.

`bom_items` stores optional `drawing_id`, optional `equipment_id`, required
`material_id`, and required `quantity NUMERIC`. Foreign keys reference
`drawings.id`, `equipment.id`, and `materials.id`. A check requires at least
one of `drawing_id` or `equipment_id`; both remain valid. Quantity must be
finite and greater than zero.

`suppliers` stores `supplier_code` and `canonical_name`.

`purchase_orders` stores required `ship_id`, optional `material_id`, optional
`equipment_id`, required `supplier_id`, `po_number`, optional `quantity`,
optional `required_date`, optional `promised_date`, optional `actual_date`,
`status`, and optional `criticality`. A check requires at least one of
`material_id` or `equipment_id`; both remain valid. No ordering constraint is
added across required, promised, and actual dates because these fields preserve
source facts.

`project_tasks` stores required `ship_id`, `task_code`, `name`, optional
planned and actual start/end dates, optional planned and actual progress, and
optional `critical_path`. Checks require each present start date not to exceed
its corresponding end date. Progress values must be finite and within the
inclusive zero-to-one range.

PostgreSQL `NUMERIC` is used without a fixed precision or scale so valid domain
Decimals round-trip exactly. Quantity checks reject zero, negatives, NaN, and
infinities. Progress checks reject values outside `0..1`, NaN, and infinities.

The schema intentionally does not invent composite cross-ship constraints that
are absent from the Task 005 domain contract.

## 5. Transactions and Errors

The caller owns the SQLAlchemy Session and its outer transaction.

`DomainRepository.insert` uses `Session.begin_nested()` and `flush()` so an
integrity failure rolls back only the insertion savepoint. The repository does
not silently commit, retry, replace, merge, or upsert data.

Unique, foreign-key, not-null, and check-constraint violations are translated
to a `DomainPersistenceError` with a stable generic message. Rejected business
or source values are not included in that message. The original
`IntegrityError` is not exposed through exception chaining.

An unsupported entity class produces a separate safe repository type error.
Connection, availability, and operational database errors are not disguised as
domain integrity failures.

## 6. Alembic Migration

The first domain revision:

1. creates tables in foreign-key dependency order;
2. creates shared source uniqueness and non-blank constraints;
3. creates all documented foreign keys and their indexes;
4. creates quantity, progress, relationship-target, text, and date-range
   checks; and
5. downgrades by dropping the tables in reverse dependency order.

`infra/postgres/migrations/env.py` imports the Declarative metadata and assigns
it to `target_metadata`, enabling future Alembic autogenerate comparison while
preserving the current online and offline modes.

The migration must generate offline PostgreSQL SQL and upgrade a fresh test
database from Alembic base to head.

## 7. PostgreSQL Integration Testing

Integration tests read only `TEST_DATABASE_URL`. They never fall back to the
application's `DATABASE_URL`.

Before running migration or cleanup operations, the test helper parses the URL
and requires the database name to end in `_test`. A missing URL causes the
PostgreSQL integration module to skip locally. A non-test database name fails
immediately without connecting. Error output must not reveal credentials.

GitHub Actions always defines `TEST_DATABASE_URL` and provisions a healthy
`pgvector/pgvector:pg16` service with synthetic credentials and a database
named `shipyard_ai_test`. Therefore CI cannot satisfy the quality gate by
skipping the PostgreSQL tests.

Integration coverage includes:

- upgrading from an empty database to Alembic head;
- the nine expected tables and Alembic revision;
- the documented foreign-key graph;
- inserting and loading a complete synthetic entity graph;
- exact UUID, source field, timezone, date, Decimal, optional-field, and
  Boolean round-trips;
- a missing canonical UUID returning `None`;
- per-table source identity uniqueness;
- canonical UUID/source ID separation;
- foreign-key, blank-text, quantity, progress, relationship-target, and date
  constraint rejection; and
- safe persistence errors that omit the rejected synthetic value.

Tests reset only the Task 006 domain revision inside the explicitly named test
database. They do not drop unrelated databases or use production credentials.

## 8. Packaging, CI, and Documentation

Because runtime code will import infrastructure modules, Task 006 adds package
initializers for `infra` and `infra.postgres`, includes `infra*` in setuptools
package discovery, and copies `infra` plus `alembic.ini` into the Docker build
context. The deployment integration test verifies that the installed artifact
can import the repository and ORM metadata from an isolated directory.

`.github/workflows/ci.yml` gains the PostgreSQL service, health check, and
synthetic `TEST_DATABASE_URL` environment variable. No unpinned Python
dependency or testcontainers dependency is added.

`infra/postgres/README.md` documents migration commands, the test-only URL
safety rule, local PostgreSQL integration-test setup, and the fact that
repository writes affect only the internal normalized store.

## 9. Expected Files

Create:

- `infra/__init__.py`
- `infra/postgres/__init__.py`
- `infra/postgres/models.py`
- `infra/postgres/repositories.py`
- `infra/postgres/migrations/versions/<revision>_create_domain_tables.py`
- `tests/integration/test_domain_repository.py`

Modify:

- `infra/postgres/migrations/env.py`
- `infra/postgres/README.md`
- `.github/workflows/ci.yml`
- `pyproject.toml`
- `Dockerfile`
- `tests/integration/test_deployment.py`

No Task 005 domain file should require modification.

## 10. Verification and Acceptance

Task 006 is complete only when:

- the first focused PostgreSQL test demonstrates RED before implementation;
- the repository integration suite passes against PostgreSQL 16/pgvector;
- Alembic upgrades an empty test database and offline SQL generation succeeds;
- all nine entities round-trip through the repository;
- canonical IDs remain distinct from source IDs;
- foreign keys match `docs/02-domain-model.md`;
- database constraints mirror the approved Task 005 invariants;
- the deployment artifact imports the infrastructure package;
- the complete pytest suite, Ruff, and mypy pass;
- an independent review has no unresolved P0, P1, or P2 finding; and
- no Task 007 behavior or real customer data is introduced.
