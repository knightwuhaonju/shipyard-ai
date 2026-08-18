# Shipyard Domain Model V1

## Canonical types and invariants

- Entity and relationship IDs are internal UUIDs; source IDs remain separate strings.
- Every entity carries source_system, source_id, and timezone-aware source_updated_at.
- Business dates use date; quantities use finite positive Decimal values.
- Progress is a finite Decimal ratio in the inclusive 0.0-1.0 range.
- Required and present optional text values are non-blank.
- Entities and constrained values are immutable.

## Canonical entities

### Ship

- id: UUID
- ship_code: string, unique business-facing code
- name: optional string
- customer_name: optional string
- vessel_type: optional string
- planned_delivery_date: optional date
- source_system
- source_id
- source_updated_at

### ShipSystem

Represents a shipboard system, such as ballast, fire, HVAC, electrical.

- id
- ship_id
- system_code
- name
- source fields

### Drawing

- id
- ship_id
- system_id optional
- drawing_no
- title
- revision
- status optional
- source fields

### Equipment

- id
- ship_id
- system_id optional
- drawing_id optional
- equipment_code
- manufacturer optional
- model optional
- source fields

### Material

- id
- material_code
- description
- specification optional
- unit optional
- source fields

### BOMItem

- id
- drawing_id optional
- equipment_id optional
- material_id
- quantity
- source fields
- BOMItem requires at least one of drawing_id or equipment_id; both are allowed.

### Supplier

- id
- supplier_code
- canonical_name
- source fields

### PurchaseOrder

- id
- ship_id
- material_id optional
- equipment_id optional
- supplier_id
- po_number
- quantity optional
- required_date optional
- promised_date optional
- actual_date optional
- status
- criticality optional
- source fields
- PurchaseOrder requires at least one of material_id or equipment_id; both are allowed.
- Purchase-order required, promised, and actual dates preserve source facts and have no ordering invariant.
- Status and criticality are non-blank strings until a controlled vocabulary is defined.

### ProjectTask

- id
- ship_id
- task_code
- name
- planned_start/end optional
- actual_start/end optional
- planned_progress optional
- actual_progress optional
- critical_path bool optional
- source fields
- ProjectTask planned and actual start dates cannot be after their corresponding end dates.

## Alias model

`EntityAlias`

- id
- entity_type
- entity_id
- alias
- normalized_alias
- source_system optional

Aliases are explicit links; they never replace canonical UUIDs.
`Wärtsilä`, `Wartsila`, and `瓦锡兰` require three stored aliases to resolve
to one Supplier. Normalization applies NFKC, case folding, and whitespace
collapse while preserving accents and punctuation. No fuzzy lookup or
automatic merge is allowed. A source-specific exact match precedes a global
fallback; a lookup without a source sees only global aliases. Supplier and
Material aliases are authenticated global master data. Equipment aliases
resolve only when the canonical Equipment belongs to the server-derived
allowed ship scope; missing and unauthorized Equipment both return no result.

## Relationship principle

V1 uses relational foreign keys. Do not introduce a graph database.

The API may expose graph-like traversal, but persistence remains relational until a demonstrated query requires otherwise.
