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

The parser contract lives in the ingestion service; format implementations are
replaceable adapters. Each adapter accepts file bytes only. A parser does not
receive a path, storage credential, authorization context, or persistence
handle, and it does not perform network, model, retrieval, chunking, or
external-process work.

Every adapter returns the same immutable `ParsedDocument`, containing ordered
immutable `ParsedBlock` values with contiguous ordinals. Blocks preserve the
source structure that later stages need: heading paths and whole rectangular
tables, XLSX sheet names, and original one-based PDF page numbers. Task 011
owns chunking; Task 010 neither chunks nor persists parser output. Parsed text
and cell values remain untrusted source data, never executable instructions.

Supported parsing behavior is deliberately bounded and deterministic:

- TXT accepts UTF-8 (including a byte-order mark) and emits non-empty
  paragraph blocks.
- Markdown recognizes a non-rendering subset of ATX and Setext headings,
  paragraphs, and rectangular pipe tables. Fenced code and raw HTML remain
  literal text.
- DOCX preserves top-level paragraph/table order, Title and Heading 1-9 paths,
  and complete rectangular tables, including deterministic merged-cell values.
- XLSX emits each non-empty worksheet as one whole table in workbook order,
  with its sheet title. Formula cells remain literal formula strings; macros
  and external links are not executed or followed.
- PDF reads only the existing text layer, emits one block per non-empty page,
  and retains the page's original one-based number. A textless PDF returns
  `OCR_REQUIRED`. OCR is disabled in Task 010; a later optional OCR adapter is
  owned by Task 012 and must preserve page provenance and the original file.

Expected failures use a typed `ParserErrorCode` and a fixed safe message:
invalid or encrypted input, unsupported text encoding, empty content, resource
limit, or OCR required. Limits are enforced before or while parsing: 25 MiB
source bytes, 10,000 blocks, 1,000,000 characters per block, 5,000,000 total
characters, and tables of at most 10,000 rows, 256 columns, and 100,000 cells.
OOXML ZIP preflight permits at most 10,000 members, 100 MiB declared
uncompressed size, and a 100:1 declared compression ratio without extracting
members. PDFs permit at most 2,000 pages and 10 MiB of decoded content-stream
data per page. Limit and parse failures do not reveal archive member names or
library exception details.

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
