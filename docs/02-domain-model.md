# Shipyard Domain Model V1

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

## Alias model

`EntityAlias`

- id
- entity_type
- entity_id
- alias
- normalized_alias
- source_system optional

Example:

Wartsila / Wärtsilä / 瓦锡兰 -> one Supplier.

## Relationship principle

V1 uses relational foreign keys. Do not introduce a graph database.

The API may expose graph-like traversal, but persistence remains relational until a demonstrated query requires otherwise.
