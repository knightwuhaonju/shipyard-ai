# Shipyard AI V1 Product Scope

## Product statement

Shipyard AI V1 is a read-mostly enterprise assistant for a medium-sized shipyard. It makes high-value information searchable, correlated, attributable, and useful for project and procurement risk analysis without replacing existing ERP/MES/PLM systems.

## Primary users

- general manager / production VP
- project manager
- procurement
- design / engineering
- process engineering
- quality
- IT / digitalization

## Initial user jobs

### Knowledge

- Find class rules, internal standards, SOPs, manuals.
- Answer with exact evidence and version information.
- Compare multiple sources without hiding conflicts.

### Project status

- Ask for status of a ship/project.
- Explain deviations using available structured signals.
- Show source system and data freshness.

### Procurement

- Show overdue items.
- Show critical items.
- Compare required date, promised date, actual date.
- Surface risk but do not auto-place orders.

### Drawing/BOM

- Traverse:
  Ship -> System -> Drawing -> Equipment -> BOM -> Material -> PO -> Supplier.

### Durable knowledge

- Convert verified repeated knowledge into Wiki pages.
- Capture decisions and lessons learned with provenance.

## V1 success metrics

Pilot target: 20-30 users.

Product metrics:

- >95% of factual document answers expose valid source references.
- zero known authorization leakage in security test suite.
- >90% expected-tool accuracy on curated deterministic tool-selection eval set.
- retrieval Recall@10 target >= 0.90 on curated knowledge questions.
- users can answer selected project/procurement questions in minutes instead of manual multi-system lookup.

Business metrics are measured in the pilot rather than hard-coded into software.

## Non-goals

See `AGENTS.md`. V1 is intentionally not a smart-yard automation/control platform.
