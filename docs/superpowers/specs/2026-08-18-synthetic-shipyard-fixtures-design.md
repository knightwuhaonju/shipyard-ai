# Task 008 Synthetic Shipyard Fixtures Design

## 1. Purpose and scope

Task 008 creates one deterministic, entirely synthetic shipyard dataset for
integration tests and future evaluation tests. The dataset covers two ships
and the canonical business relationships introduced by Tasks 005-007:

```text
Ship -> ShipSystem -> Drawing -> Equipment -> BOMItem -> Material
Ship -> PurchaseOrder -> Supplier
Ship -> ProjectTask
Supplier / Equipment / Material <- EntityAlias
```

The task also adds a reusable loader that can either return immutable domain
objects without a database or persist the same objects into PostgreSQL through
the existing repositories.

This task does not add production seed data, an application API, an Agent tool,
a business-risk service, document fixtures, Task 009 schema, or any write path
to ERP/MES/PLM.

## 2. Architecture boundaries

- Fixture data and loader code live only under `tests/fixtures`.
- The loader constructs the existing framework-independent domain types and
  authentication contracts; it does not create parallel production models.
- PostgreSQL persistence uses `DomainRepository` and `AliasRepository` rather
  than SQLAlchemy models or generated SQL.
- The persistence operation receives a caller-owned SQLAlchemy `Session`, uses
  an outer savepoint for dataset atomicity, and never commits.
- Canonical UUIDs remain different from `source_id` values.
- Every sourced entity has `source_system`, `source_id`, and a timezone-aware
  `source_updated_at`.
- Alias normalization and lookup remain owned by Task 007. The fixture loader
  creates explicit `EntityAlias` objects and never performs fuzzy matching.
- Security contexts are test inputs created as `UserContext` values. They are
  not accepted from model output and do not weaken service authorization.
- No network call, external model, customer file, or production credential is
  used by fixture loading or tests.

Allowed dependency direction for this test utility is:

```text
tests.fixtures -> packages.domain / packages.contracts
tests.fixtures persistence helper -> infra.postgres public repositories
tests.integration -> tests.fixtures + services + infra
```

No production package imports `tests.fixtures`.

## 3. Dataset identity and synthetic-data policy

`manifest.json` identifies the dataset with:

- `dataset_id = "synthetic-shipyard-v1"`
- integer `dataset_version = 1`
- `synthetic = true`
- fixed `as_of_date = "2026-08-18"`
- named expected purchase-order cases
- the two required security-scope names

All sourced records use exactly `source_system = "synthetic-fixture"` and a
`source_id` beginning with `synthetic:`. UUIDs are fixed literals in a Task 008
namespace and never derive from source IDs.

Names visibly identify synthetic data. Examples include `Synthetic Vessel
Alpha`, `Synthetic Customer Alpha`, and fictional suppliers such as `Synthetic
Northstar Marine Systems`. The Task 007 real-brand spelling example is not
copied into this dataset. No real shipyard, customer, vessel, hull number,
supplier account, purchase order, price, credential, or customer document is
present.

The loader rejects a dataset when:

- the manifest does not explicitly declare `synthetic = true`;
- a sourced record uses another source system;
- a source ID lacks the `synthetic:` prefix; or
- a required manifest case or scope does not point to a loaded record.

These checks supplement human review; they are not presented as a general
real-data detection system.

## 4. File layout and JSON contracts

The dataset is split by domain type so records remain reviewable and later
tests can inspect one concern without parsing an unrelated monolith:

```text
tests/fixtures/
  __init__.py
  loader.py
  README.md
  shipyard/
    manifest.json
    ships.json
    ship_systems.json
    drawings.json
    equipment.json
    materials.json
    bom_items.json
    suppliers.json
    purchase_orders.json
    project_tasks.json
    aliases.json
    security_scopes.json
```

Each entity file contains a JSON array. Records use field names matching the
domain constructors. JSON representations are intentionally strict:

- UUIDs are lowercase canonical UUID strings;
- dates are ISO `YYYY-MM-DD` strings;
- datetimes are ISO 8601 strings with an explicit UTC offset;
- decimal quantities and progress values are JSON strings, never floats;
- optional values use JSON `null`;
- unknown and missing fields are rejected; and
- array order is preserved in the returned immutable tuples.

`aliases.json` records `id`, `entity_type`, `entity_id`, `alias`, and optional
`source_system`. It never accepts a caller-supplied `normalized_alias`; the
domain object computes that value.

`security_scopes.json` records a stable fixture name plus fields accepted by
`UserContext`. Security clearance uses the enum name rather than a magic
integer. The two names are:

- `ship-alpha-only`
- `ship-beta-only`

Each context contains exactly its own ship UUID in `allowed_ship_ids` and not
the other ship. Project scope is empty because Task 008 introduces no Project
entity.

## 5. Minimum scenario graph

The checked-in dataset contains at least:

- 2 Ships;
- 2 ShipSystems, one per ship;
- 2 Drawings, one per ship;
- 2 Equipment records, one per ship;
- 2 Materials;
- 2 BOMItems joining the drawings/equipment to materials;
- 2 fictional Suppliers;
- 4 PurchaseOrders, with records on both ships;
- 4 ProjectTasks, two per ship; and
- 5 explicit aliases: three multilingual/abbreviated Supplier aliases and one
  Equipment alias per ship.

The purchase-order scenarios are evaluated against the manifest's fixed
`as_of_date`, not the machine clock:

- at least one OPEN order has no `actual_date` and a `promised_date` before
  `as_of_date` (overdue);
- at least one OPEN order has no `actual_date` and a `promised_date` on or
  after `as_of_date` (non-overdue);
- at least one DELIVERED order has an `actual_date`; and
- expected record UUIDs are listed in the manifest so future risk/eval tests
  can assert stable outcomes without attaching fixture-only labels to domain
  records.

Dates remain source facts. The loader does not invent a new PurchaseOrder date
ordering invariant or implement business-risk calculations.

## 6. Loader public contract

`tests.fixtures.loader` exposes:

```python
class FixtureValidationError(ValueError): ...

@dataclass(frozen=True, slots=True)
class PurchaseOrderCases:
    overdue_ids: frozenset[UUID]
    non_overdue_ids: frozenset[UUID]
    delivered_ids: frozenset[UUID]

@dataclass(frozen=True, slots=True)
class NamedUserContext:
    name: str
    user_context: UserContext

@dataclass(frozen=True, slots=True)
class ShipyardFixtureSet:
    dataset_id: str
    dataset_version: int
    as_of_date: date
    ships: tuple[Ship, ...]
    ship_systems: tuple[ShipSystem, ...]
    drawings: tuple[Drawing, ...]
    equipment: tuple[Equipment, ...]
    materials: tuple[Material, ...]
    bom_items: tuple[BOMItem, ...]
    suppliers: tuple[Supplier, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    project_tasks: tuple[ProjectTask, ...]
    aliases: tuple[EntityAlias, ...]
    security_contexts: tuple[NamedUserContext, ...]
    purchase_order_cases: PurchaseOrderCases

def load_shipyard_fixture_set(
    root: Path | None = None,
) -> ShipyardFixtureSet: ...

def persist_shipyard_fixture_set(
    session: Session,
    fixture_set: ShipyardFixtureSet,
) -> None: ...
```

The default root is the checked-in `tests/fixtures/shipyard` directory. An
explicit root enables malformed-dataset tests using a temporary copy. The
loader reads only the named JSON files beneath that explicit root; it does not
scan arbitrary directories.

The returned fixture set is immutable at its public boundaries. Repeated loads
from unchanged files compare equal and preserve the same tuple order.

`tests/fixtures/__init__.py` exports the six public names above. The package is
test-only and is not added to the installed application artifact.

## 7. Validation and failure behavior

The loader performs validation before returning or opening a persistence
savepoint:

1. validate manifest identity, version, synthetic marker, and fixed date;
2. parse every file with strict expected keys and types;
3. construct existing domain objects and `UserContext` values;
4. reject duplicate canonical UUIDs across the entire dataset;
5. reject duplicate `(source_system, source_id)` pairs across records of the
   same canonical type;
6. validate every domain relationship against the relevant loaded ID set;
7. ensure each alias targets an existing entity of its declared type;
8. ensure there are exactly the two manifest-named security contexts, each
   names an existing ship, and their allowed ship sets are mutually isolated;
9. ensure manifest case IDs refer to PurchaseOrders and satisfy the declared
   overdue/non-overdue/delivered scenario relative to `as_of_date`.

Invalid JSON, schema/type errors, domain validation failures, duplicate IDs,
broken references, and invalid manifest expectations become
`FixtureValidationError`. Messages contain only a relative file name, array
index when applicable, and a fixed reason category. They do not include the
raw record, an absolute path, connection details, or environment values.

The loader does not attempt partial recovery, infer missing values, coerce
floating-point numbers to Decimal, fix aliases, or silently drop invalid
records.

## 8. Persistence behavior

`persist_shipyard_fixture_set` uses one outer `Session.begin_nested()` block
and inserts through public repositories in foreign-key order:

1. Ships
2. ShipSystems
3. Drawings
4. Equipment
5. Materials
6. Suppliers
7. BOMItems
8. PurchaseOrders
9. ProjectTasks
10. EntityAliases

The load and persistence paths call the same fixture-set relationship and
scenario validator. This prevents a caller from manually constructing an
invalid public `ShipyardFixtureSet` and bypassing validation before database
work begins.

The outer savepoint makes one fixture-set load atomic even though the existing
repositories also protect individual inserts with nested savepoints. Any
repository error propagates after rolling back the complete dataset load. The
caller's outer Session remains usable.

The function never commits, updates, deletes, truncates, calls metadata
`create_all`, or performs an upsert. Loading the same fixture set twice into
the same database is an explicit constraint failure rather than an idempotent
overwrite.

## 9. Security-scope use

The dataset carries two trusted test contexts, not an authorization bypass.
Integration tests wire the persisted `AliasRepository` and canonical Equipment
lookup into `EntityResolutionService` and verify:

- `ship-alpha-only` resolves the Alpha Equipment alias;
- `ship-alpha-only` receives `None` for the Beta Equipment alias;
- `ship-beta-only` has the inverse behavior; and
- an unregistered near-spelling returns `None` and creates no alias.

Supplier and Material aliases remain global according to Task 007 policy.
Equipment authorization continues to execute in the service layer.

## 10. Testing strategy

All Task 008 behavior is exercised in
`tests/integration/test_fixture_loader.py`.

TDD slices cover:

- deterministic file loading and immutable typed output;
- exact record counts and complete two-ship relationship graph;
- synthetic provenance, distinct canonical/source IDs, and timezone-aware
  source timestamps;
- fixed-date overdue, non-overdue, and delivered cases;
- strict alias parsing and no fuzzy resolution;
- both mutually isolated Equipment security scopes;
- PostgreSQL persistence and complete repository round trips;
- caller-owned transaction behavior;
- whole-dataset rollback plus reusable Session after a persistence failure;
- malformed JSON/schema, non-synthetic provenance, duplicate IDs, broken
  references, and invalid manifest expectations; and
- deterministic repeated loads.

PostgreSQL tests reuse the existing guarded `migrated_session` fixture. They
run only against the exact approved `shipyard_ai_test` database. All records
remain synthetic, and no unit or integration test uses network or an external
model.

The final gate includes:

- the focused fixture-loader integration module with zero skips;
- existing domain, alias, authorization, and deployment suites;
- the complete pytest suite;
- Ruff;
- mypy; and
- diff hygiene against the branch base.

No migration is required because Task 008 adds test data and test utilities,
not database schema.

## 11. Documentation

`tests/fixtures/README.md` documents:

- the synthetic-only guarantee;
- dataset version and fixed `as_of_date`;
- file layout;
- pure-load and caller-transaction-owned persistence examples;
- explicit alias and security-scope semantics;
- the non-idempotent duplicate-load behavior; and
- the protected PostgreSQL test command.

Production product/architecture documents do not change because no production
contract or subsystem is added.

## 12. Expected files

Create:

- `tests/fixtures/__init__.py`
- `tests/fixtures/loader.py`
- `tests/fixtures/README.md`
- `tests/fixtures/shipyard/manifest.json`
- `tests/fixtures/shipyard/ships.json`
- `tests/fixtures/shipyard/ship_systems.json`
- `tests/fixtures/shipyard/drawings.json`
- `tests/fixtures/shipyard/equipment.json`
- `tests/fixtures/shipyard/materials.json`
- `tests/fixtures/shipyard/bom_items.json`
- `tests/fixtures/shipyard/suppliers.json`
- `tests/fixtures/shipyard/purchase_orders.json`
- `tests/fixtures/shipyard/project_tasks.json`
- `tests/fixtures/shipyard/aliases.json`
- `tests/fixtures/shipyard/security_scopes.json`
- `tests/integration/test_fixture_loader.py`

No production source, migration, Task 009 file, application API, or Agent
package is modified.

## 13. Acceptance mapping

- No real company/customer data: enforced by fictional visible names,
  `synthetic = true`, exact synthetic source rules, tests, and human diff
  review.
- Overdue and non-overdue procurement: represented by fixed manifest cases
  evaluated against `2026-08-18` rather than wall-clock time.
- Alias cases and two security scopes: explicit fictional Supplier/Equipment
  aliases plus mutually isolated Alpha/Beta `UserContext` values.
- Reusable loader: one immutable in-memory contract plus optional atomic,
  caller-transaction-owned repository persistence for integration/eval tests.
