# Task 1 report: checked-in synthetic dataset contract

## Implementation

- Added the raw integration contract test in `tests/integration/test_fixture_loader.py`.
- Added the fixed synthetic dataset manifest and all eleven JSON entity/scope files under `tests/fixtures/shipyard/`.
- Preserved the required UUIDs, array order, source provenance values, relationship IDs, nullable fields, decimal strings, dates, aliases, security scopes, and manifest purchase-order cases.
- No loader, production code, migrations, or Task 009 work was added.

## TDD RED/GREEN evidence

RED command:

```text
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py::test_checked_in_dataset_has_stable_synthetic_manifest_and_counts -v
```

Result: failed as expected with `FileNotFoundError` for `tests/fixtures/shipyard/manifest.json` before the fixture files existed.

GREEN command (same command after adding the dataset):

Result: `1 passed in 0.01s`.

## Additional checks

- `git diff --check`: passed with exit code 0.
- Parsed every checked-in JSON file with Python's JSON parser and confirmed counts: aliases 5, bom_items 2, drawings 2, equipment 2, materials 2, project_tasks 4, purchase_orders 4, security_scopes 2, ship_systems 2, ships 2, suppliers 2.

## Files changed

- `tests/integration/test_fixture_loader.py`
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

## Self-review

- Confirmed JSON keys follow the existing domain constructor field names inspected in `packages/domain/entities.py`, `packages/domain/aliases.py`, and `packages/contracts/auth.py`.
- Confirmed all sourced records use `synthetic-fixture`, a `synthetic:` source ID, and the fixed UTC timestamp.
- Confirmed all requested nullable fields are explicit, including purchase-order material/equipment/actual dates and project-task actual dates.
- Confirmed no real customer, shipyard, supplier, credential, or production data is present.
- Confirmed the focused test only checks the raw checked-in contract, as required for this slice.

## Concerns

- Ruff, mypy, and the full repository suite were not run because this slice's brief specifies the focused raw contract test; loader-dependent tests are intentionally deferred to the later loader slice.

## Commits

- `0c15ea5455e60fb894131888d59a8ab3114950cb` — `test: add deterministic synthetic shipyard dataset`
