# Synthetic shipyard fixtures

`tests/fixtures` provides one deterministic dataset for integration tests and
future evaluation tests. It is **synthetic-only**: version 1 is fixed at
`2026-08-18`, declares `synthetic: true` in its manifest, and contains no real
customer or company data. Its stable identity is
`synthetic-shipyard-v1`.

Every sourced record uses `source_system = "synthetic-fixture"`, a
`source_id` that begins with `synthetic:`, and a timezone-aware
`source_updated_at`. Canonical UUIDs are fixed internal identifiers and remain
separate from source IDs.

## Pure loading

Use the public test-only package to read the immutable typed graph without a
database:

```python
from tests.fixtures import load_shipyard_fixture_set

fixtures = load_shipyard_fixture_set()
assert fixtures.dataset_id == "synthetic-shipyard-v1"
```

Repeated loads of unchanged checked-in files compare equal and preserve JSON
array order in immutable tuples. Pass an explicit fixture-root `Path` only for
tests that deliberately load a temporary malformed copy; the loader reads only
the named files below that root.

## Persistence

Persist through the public repository layer with a caller-owned SQLAlchemy
transaction:

```python
from sqlalchemy.orm import Session

from tests.fixtures import load_shipyard_fixture_set, persist_shipyard_fixture_set

with Session(engine) as session, session.begin():
    persist_shipyard_fixture_set(session, load_shipyard_fixture_set())
    # The caller decides whether the outer transaction commits or rolls back.
```

Persistence validates the complete fixture graph before opening its savepoint,
then inserts through `DomainRepository` and `AliasRepository` in foreign-key
order. It never commits, updates, deletes, truncates, creates schema, or
upserts. A duplicate load into the same database intentionally raises the
repository constraint error rather than overwriting the original records. If a
repository insert fails, the whole fixture-set savepoint rolls back and the
caller-owned session remains usable.

## Files

The loader requires exactly these JSON files beneath `tests/fixtures/shipyard`:

```text
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

The manifest fixes `dataset_id` to `synthetic-shipyard-v1`,
`dataset_version` to `1`, and `as_of_date` to `2026-08-18`. It also declares
the expected purchase-order case IDs: one overdue open order, two non-overdue
open orders (including the date boundary), and one delivered order. These are
evaluated against the fixed manifest date, never the machine clock.

JSON is strict: UUIDs are canonical lowercase strings, dates and timezone-aware
datetimes use ISO formats, decimal values are strings, and unknown or missing
fields are rejected. Before returning data or writing anything, the loader
validates manifest identity and provenance, types, domain construction,
duplicate IDs/sources, relationships, alias targets, the two isolated security
scopes, and the declared purchase-order cases. Invalid data raises
`FixtureValidationError`; it is never coerced, repaired, or partially loaded.

## Aliases and security scopes

Aliases are explicit records, not search guesses. The five stored aliases are:

- Supplier: `Synthetic Northstar Marine Systems`, `SNMS`, and `合成北星船舶系统`
  for the same synthetic supplier.
- Equipment: `Synthetic Alpha Main Cooling Pump` for Alpha and `Synthetic Beta
  Main Generator` for Beta.

The Task 007 alias normalizer owns exact normalized lookup (case, Unicode, and
whitespace normalization); this fixture loader creates `EntityAlias` records
only. It performs no fuzzy matching, automatic alias creation, or merge. For
example, the unregistered near-spelling `Synthetic Alpha Main Cooling Pumps`
does not resolve.

`security_scopes.json` defines exactly two trusted test `UserContext` inputs:

- `ship-alpha-only` contains only Alpha's ship UUID.
- `ship-beta-only` contains only Beta's ship UUID.

The scopes are mutually isolated and have no project IDs. Equipment alias
resolution is still authorized in the service layer: each context can resolve
its own ship's equipment alias but receives no result for the other ship's
alias. These contexts are fixture inputs, not model-supplied identities or an
authorization bypass.

## Protected integration command

The PostgreSQL integration module is intentionally guarded. Run it only
against the approved local test database:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test .venv/bin/python -m pytest tests/integration/test_fixture_loader.py -v
```

Do not replace this connection target with a production or other database.
