# Shipyard AI V1 Architecture

## 1. High-level architecture

```text
                         User
                          |
                    Pilot Web UI
                          |
                    API / AuthN
                          |
                   Shipyard Agent
                          |
          +---------------+----------------+
          |               |                |
   Knowledge Tools   Business Tools   Analysis/Risk Tool
          |               |                |
      Retrieval        Tool Server         |
       + Wiki              |               |
          |         Approved services      |
          |               |                |
   PostgreSQL       Read-only adapters     |
   + pgvector        ERP/MES/PLM replica   |
          |
   Object Storage
```

## 2. Logical planes

### Knowledge plane

- ingestion
- document/version metadata
- chunks
- lexical retrieval
- vector retrieval
- reranking
- citation assembly
- Wiki

### Business plane

- canonical domain entities
- typed tools
- read-only source adapters
- source timestamps
- risk feature calculation

### Agent plane

- intent routing
- bounded plan generation
- tool calls
- evidence aggregation
- answer synthesis

### Governance plane

- authentication
- authorization scope
- audit
- eval
- provenance

## 3. Source-of-truth matrix

| Data | Authoritative source | Agent access |
|---|---|---|
| current PO state | ERP/read replica | typed procurement tool |
| current project status | MES/project system | typed project tool |
| drawing metadata | PLM / approved replica | drawing/BOM tool |
| class rules | original document/version | retrieval |
| internal SOP | original approved doc | retrieval |
| lessons learned | verified/canonical Wiki + evidence | Wiki tool |
| model conclusion | none | must be labeled inference |

## 4. Service boundaries

### ingestion

Owns:
- raw file normalization
- document versions
- parsing/chunking pipeline

Does not own:
- answer generation
- business SQL
- Agent planning

### retrieval

Owns:
- lexical/vector indexes
- hybrid ranking
- ACL-aware search
- Evidence objects

### wiki

Owns:
- pages
- revisions
- claims
- links
- provenance
- review lifecycle

### tool_server

Owns:
- typed business capability contracts
- authorization enforcement
- audit trail
- adapter orchestration

### agent

Owns:
- routing
- tool planning
- evidence aggregation
- response synthesis

Does not own:
- ERP schema knowledge
- file parsing
- Wiki canonicalization approval

## 5. Deployment V1

Docker Compose services:

- api
- postgres + pgvector
- object-store
- web

Additional workers may initially run in the API process for development, but ingestion must be coded behind a job interface so it can move to a worker later without changing its domain contract.

## 6. Failure policy

- business tool timeout: report unavailable/stale, do not invent result
- retrieval empty: say evidence not found
- conflicting sources: surface conflict
- model failure: preserve tool/evidence trace and return graceful error
- missing authorization scope: deny
- stale source timestamp: show staleness
