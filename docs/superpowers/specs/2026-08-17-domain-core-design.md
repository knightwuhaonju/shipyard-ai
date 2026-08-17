# Task 005 Core Domain Design

## Scope

Task 005 introduces the framework-independent, immutable V1 shipyard domain
model for `Ship`, `ShipSystem`, `Drawing`, `Equipment`, `Material`, `BOMItem`,
`Supplier`, `PurchaseOrder`, and `ProjectTask`.

The task defines domain values and invariants only. It does not add SQLAlchemy
models, repositories, migrations, aliases, synthetic fixture datasets, API
routes, source adapters, or any Task 006 behavior.

## Architecture Constraints

- The domain package depends only on the Python standard library. It does not
  import FastAPI, Pydantic, SQLAlchemy, database drivers, or LLM SDKs.
- ERP, MES, PLM, and approved replicas remain the source of truth for live
  business state. Domain entities are normalized representations, not new
  authoritative sources.
- Every entity carries `source_system`, `source_id`, and `source_updated_at`
  directly as fields.
- Canonical `id` and relationship IDs are internal UUIDs. External source IDs
  remain separate non-blank strings.
- The model follows the relationships and fields in `docs/02-domain-model.md`.
- Entities are immutable and validate their invariants at construction time.
- Unit tests are deterministic, synthetic, offline, and make no model calls.

## Chosen Approach

Use frozen, slotted, keyword-only standard-library dataclasses for entities and
small frozen value objects for constrained numeric values. This keeps the
domain independent from transport and persistence frameworks while preventing
partially valid objects from entering services.

Pydantic remains appropriate for cross-service contracts, but Task 005 domain
entities do not depend on it. Validation does not live in a separate service,
because doing so would allow invalid entities to exist between construction and
validation.

## Value Objects

`packages/domain/value_objects.py` defines:

- `DomainValidationError`, a `ValueError` subtype for violated domain rules.
- `PositiveQuantity`, an immutable wrapper around `Decimal`. Its value must be
  finite and strictly greater than zero.
- `Progress`, an immutable wrapper around `Decimal`. Its value must be finite
  and between `Decimal("0")` and `Decimal("1")`, inclusive.

Both numeric value objects accept `Decimal` only. Adapters must convert source
integers, percentages, strings, or floats before constructing domain values.
This avoids implicit binary floating-point behavior in quantities and progress.

Validation messages identify the field and the violated rule without including
the rejected value or customer/source content.

## Entity Structure

`packages/domain/entities.py` defines a private frozen, slotted, keyword-only
base dataclass that provides these direct fields to every public entity:

- `id: UUID`
- `source_system: str`
- `source_id: str`
- `source_updated_at: datetime`

The base validates that `id` is a UUID, source strings are non-blank, and
`source_updated_at` is timezone-aware with a defined UTC offset.

The nine public entities contain the following fields.

`packages/domain/__init__.py` re-exports the nine entities plus
`DomainValidationError`, `PositiveQuantity`, and `Progress`. The private sourced
base and validation helpers are not part of the public API.

### Ship

- required: `ship_code`
- optional: `name`, `customer_name`, `vessel_type`, `planned_delivery_date`

### ShipSystem

- required: `ship_id`, `system_code`, `name`

### Drawing

- required: `ship_id`, `drawing_no`, `title`, `revision`
- optional: `system_id`, `status`

### Equipment

- required: `ship_id`, `equipment_code`
- optional: `system_id`, `drawing_id`, `manufacturer`, `model`

### Material

- required: `material_code`, `description`
- optional: `specification`, `unit`

### BOMItem

- required: `material_id`, `quantity`
- optional individually: `drawing_id`, `equipment_id`
- invariant: at least one of `drawing_id` or `equipment_id` is present; both
  are allowed

### Supplier

- required: `supplier_code`, `canonical_name`

### PurchaseOrder

- required: `ship_id`, `supplier_id`, `po_number`, `status`
- optional: `material_id`, `equipment_id`, `quantity`, `required_date`,
  `promised_date`, `actual_date`, `criticality`
- invariant: at least one of `material_id` or `equipment_id` is present; both
  are allowed
- no ordering rule is applied across required, promised, and actual dates,
  because lateness and source-system anomalies are valid business facts to
  preserve

### ProjectTask

- required: `ship_id`, `task_code`, `name`
- optional: `planned_start`, `planned_end`, `actual_start`, `actual_end`,
  `planned_progress`, `actual_progress`, `critical_path`
- invariants: a present planned start cannot be after a present planned end;
  the same rule applies to actual start and end

## Shared Field Rules

- Required text fields are strings containing at least one non-whitespace
  character.
- Optional text fields, when present, follow the same non-blank rule.
- Canonical and relationship IDs must be UUID instances; strings cannot replace
  internal IDs even if they contain UUID text.
- Business date fields use `datetime.date` and reject `datetime.datetime`.
- Source freshness uses timezone-aware `datetime.datetime`.
- `BOMItem.quantity` and optional `PurchaseOrder.quantity` use
  `PositiveQuantity`.
- Task progress fields use `Progress` and therefore the canonical `0.0-1.0`
  scale.
- Optional `critical_path`, when present, must be a real `bool`.
- Status and criticality remain non-blank strings because V1 documentation does
  not define a controlled vocabulary. Task 005 does not invent one.

## Data Flow and Boundaries

1. A future read-only ERP/MES/PLM adapter receives source records.
2. The adapter converts source identifiers, dates, quantities, and percentage
   progress into the canonical standard-library and value-object types.
3. The adapter constructs an immutable domain entity with a separate internal
   UUID and explicit source metadata.
4. Domain construction rejects invalid normalized state immediately.
5. Services consume immutable entities and continue to treat the recorded
   source system and freshness timestamp as provenance.
6. Task 006 persistence code maps database rows to and from these entities. The
   domain package never imports or calls persistence code.

## Failure Behavior

- Invalid domain state raises `DomainValidationError` during construction.
- Errors name the field and rule but omit the invalid value.
- Missing BOM or purchase-order targets fail rather than creating untraceable
  relationship records.
- Invalid date ranges and progress values fail rather than being silently
  clamped or reordered.
- Purchase-order delivery dates are preserved as received after type
  normalization, even when they expose delay or inconsistent source state.

## Testing Strategy

Development follows RED-GREEN-REFACTOR for each behavior group:

1. Write a failing test that imports and constructs all nine entity types with
   one coherent synthetic shipyard graph.
2. Add the minimum base/entity fields and confirm every entity exposes all
   source fields with canonical UUIDs separate from source IDs.
3. Add focused failing tests for numeric value objects, then implement finite
   positive quantities and canonical `0-1` progress.
4. Add focused failing tests for blank text, UUID types, timezone awareness,
   date types and ranges, BOM/PO targets, and immutability; implement only the
   validation required by each test group.
5. Add a static import-boundary test that scans every Python module under
   `packages/domain` and rejects FastAPI, Pydantic, SQLAlchemy, database-driver,
   or LLM-SDK imports.

All fixtures use synthetic identifiers and names. Verification runs the focused
domain test module, the complete unit suite, relevant existing integration
tests, `ruff check .`, and `mypy .`.

## Documentation

`docs/02-domain-model.md` will be updated to make the chosen UUID, date,
timezone, quantity, progress, relationship, and validation rules public for
later adapters and persistence work. No ADR is needed because the decision
clarifies the existing domain architecture without changing subsystem
direction.

## Expected Changes

- `packages/domain/__init__.py`
- `packages/domain/value_objects.py`
- `packages/domain/entities.py`
- `tests/unit/domain/test_entities.py`
- `docs/02-domain-model.md`
- `docs/superpowers/plans/2026-08-17-domain-core.md`

The existing `packages*` package discovery and Docker `COPY packages` rule
already include `packages/domain`, so no build configuration or migration is
required.

## Acceptance Mapping

- Framework independence: domain imports are standard-library only and a static
  import-boundary test protects the rule.
- Source fields: every public entity inherits direct `source_system`,
  `source_id`, and `source_updated_at` fields from the private base.
- Domain invariants: tests cover identifiers, text, timezones, numeric values,
  relationship completeness, dates, progress, and immutability.

## Known Limitations

- Task 005 does not persist entities or provide repositories/migrations.
- It does not normalize aliases or source-system field formats.
- It does not define status or criticality vocabularies.
- It does not perform authorization; services must enforce authorization before
  exposing domain records.
- Cross-record existence and foreign-key integrity require Task 006 persistence
  and cannot be proven by isolated domain objects.
