# Knowledge System Design

## 1. Document model

Document:
- stable logical source identity; its internal ID is not replaced by a
  source-system ID

DocumentVersion:
- immutable content and authorization snapshot
- uniquely identified per Document and SHA-256 checksum
- source URI and source-updated time
- ship, project, department, and security-level ACL metadata
- parsed artifact references
- an identical retry returns the stored Version only when all immutable
  metadata agrees; otherwise the registration conflicts and does not overwrite
  the stored Version

DocumentChunk:
- deterministic UUIDv5 ID over canonical JSON containing version, structural
  path, and ordinal
- structural metadata
- page/section
- normalized text
- inherits its ACL through its Version

An empty structural path is reserved for the unstructured fallback. Embeddings
are not stored by this document metadata schema; Task 014 owns embedding
storage.

## 2. Ingestion

```text
discover file
  -> hash
  -> identify document/version
  -> parse
  -> normalize
  -> extract structural metadata
  -> chunk
  -> persist
  -> lexical index
  -> embedding
```

V1 parsers:

- PDF
- DOCX
- XLSX
- TXT
- Markdown

OCR is an adapter. Scanned-PDF OCR output must remain linked to page numbers and original file.

## 3. Chunking

Default to structure-aware chunking:

- heading
- chapter
- section
- subsection
- table region
- paragraph group

Do not cut purely by fixed token count unless no structural information exists.

Chunks must be re-creatable deterministically from the same immutable version.

## 4. Retrieval

```text
query
 -> authorization scope
 -> metadata filters
 -> lexical candidates
 -> vector candidates
 -> merge
 -> rerank
 -> Evidence[]
```

V1 target interface:

```python
retrieve(
    query: str,
    user_scope: AuthorizationScope,
    filters: KnowledgeFilters,
    limit: int = 10,
) -> list[KnowledgeEvidence]
```

## 5. Evidence

KnowledgeEvidence contains:

- document_id
- version_id
- chunk_id
- title
- section
- page
- source_uri
- excerpt
- lexical_score optional
- vector_score optional
- rerank_score optional

## 6. Wiki

Wiki provides synthesized durable knowledge, not live state.

Core records:

- WikiPage
- WikiRevision
- WikiClaim
- WikiSource
- WikiLink

Every claim has provenance.

Generated content is DRAFT until reviewed.

## 7. Query priority

For a mature knowledge topic:

1. Wiki for synthesized understanding
2. raw retrieval for exact evidence/verification
3. business tools for live state

The final answer may combine all three but must label evidence type.
