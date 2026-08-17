# Shipyard Tool Contracts V1

All tools receive an authenticated `UserContext`. User identity is injected by the host service, never accepted from model arguments.

## Common types

```text
UserContext
- user_id
- roles[]
- departments[]
- allowed_ship_ids[]
- allowed_project_ids[]
- security_clearance

ToolEvidence
- source_system
- source_record_ids[]
- source_updated_at
- query_time
```

## 1. search_knowledge

Input:
- query
- optional ship_id
- optional project_id
- optional document_type
- limit <= 20

Output:
- evidence[]

## 2. search_wiki

Input:
- query
- optional entity filters
- statuses allowed by caller

Output:
- pages/claims + provenance

## 3. get_ship_status

Input:
- ship_id

Output:
- high-level project status
- milestones
- progress signals
- evidence

## 4. get_procurement_status

Input:
- ship_id
- overdue_only
- critical_only
- optional supplier_id

Output:
- summary counts
- items[]
- evidence

## 5. get_drawing_bom

Input:
- drawing_id OR ship_id + drawing_no

Output:
- drawing
- equipment[]
- bom_items[]
- related materials
- evidence

## 6. get_risk_summary

Input:
- ship_id

Output:
- deterministic risk items
- severity
- reason codes
- supporting business evidence

## Transport

Business contracts are transport-independent.

An MCP adapter may expose approved tools later. MCP-specific concerns must not leak into domain/service interfaces.
