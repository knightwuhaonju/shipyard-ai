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
- PDF parsing remains text-layer-first, emits one block per non-empty page,
  and retains the page's original one-based number. A textless PDF returns
  `OCR_REQUIRED`. `OcrFallbackParser` remains disabled unless an `OcrPort` is
  explicitly injected, and only `OCR_REQUIRED` invokes that port. Successful
  results become normalized PDF `PAGE` blocks with original page numbers and
  contiguous ordinals.

Task 012 adds no real OCR engine. Its deterministic fake exists only for local
contract tests. OCR text is a derived, untrusted parsing artifact; the original
PDF and immutable document version remain authoritative. OCR orchestration
accepts bytes only and does not persist, chunk, retrieve, authorize, use paths,
make external calls, or replace document/version provenance.

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

`StructuralChunker` is a pure ingestion service with the boundary
`ParsedDocument -> tuple[DocumentChunk, ...]`. It reads no files and performs
no persistence. The default limit is 2,000 normalized Unicode characters per
chunk and callers may configure another positive character limit. It does not
use a tokenizer, so chunk boundaries are independent of model vendors.

The chunker prefers parser-provided structure over size-only splitting:

- same-context paragraphs group in source order, where context is the
  structural path and page;
- each body chunk normally includes its full heading-path prefix, while the
  most specific path element becomes `section`;
- PDF `PAGE` blocks keep their original one-based page number through every
  split and never merge across pages;
- an empty-path region uses a local unstructured fallback without changing how
  later structured regions are chunked; and
- a canonical TSV table stays whole when it fits. Only an oversized table uses
  maximal consecutive row groups with the first row repeated as retrieval
  context. If a non-blank header fits but cannot share a chunk with one
  oversized data row, the header is emitted as a standalone context chunk
  immediately before that row's fragments and is repeated for each such row.
  An empty or all-whitespace header never creates a blank chunk. The current
  legal parser `TABLE` contract does not carry a page.

Canonical all-empty table rows are preserved when they fit inside a non-blank
table chunk. If an all-empty row could only be emitted as a standalone
whitespace-only chunk, it is omitted because `DocumentChunk` forbids blank
text and split-boundary whitespace is discarded. Representing that boundary
independently would require a future, deliberate domain-contract change.

Oversized structural units split deterministically at newline, then other
Unicode whitespace, then exact Unicode code-point boundaries. There is no
overlap. Final ordinals are global and contiguous, and each Chunk ID is the
existing deterministic UUIDv5 over version, structural path, and ordinal. The
same immutable version, parsed document, and configuration therefore recreate
equal chunks and IDs.

Chunking has no tokenizer, model, OCR, network, filesystem, persistence, or
authorization behavior. ACL metadata remains on `DocumentVersion` and is
inherited through `version_id`; authorization is enforced by later retrieval
services. Optional OCR output reaches the chunker only through the existing
`ParsedDocument` contract; the chunker itself has no OCR behavior.

## 4. Retrieval

Task 013 provides ACL-filtered lexical retrieval over every authorized
immutable document version. It does not choose a current version because the
document model has no current-version lifecycle marker.

The shared immutable document-format contract is exactly:

```python
class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    TXT = "txt"
    MARKDOWN = "markdown"
```

The frozen, transport-independent public request and result contracts are:

```python
class KnowledgeFilters:
    document_type: DocumentType | None = None
    ship_id: UUID | None = None
    project_id: UUID | None = None


class KnowledgeEvidence:
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: str
    section: str | None = None
    page: int | None = None
    source_uri: str
    excerpt: str
    retrieval_score: float
    lexical_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None
```

The service-owned port and validated service entry point are:

```python
search(
    query: str,
    user_scope: AuthorizationScope,
    filters: KnowledgeFilters,
    limit: int,
) -> list[KnowledgeEvidence]

retrieve(
    query: str,
    user_scope: AuthorizationScope,
    filters: KnowledgeFilters,
    limit: int = 10,
) -> list[KnowledgeEvidence]
```

The query is stripped and must be a non-empty, NUL-free exact string of at
most 1,000 Unicode code points. The limit must be an exact integer from 1
through 20. `AuthorizationScope` is computed server-side and passed separately
from caller filters.

Authorization is part of the PostgreSQL candidate predicate before ranking,
ordering, and `LIMIT`:

```text
version.security_level <= scope.security_level
AND (version.department IS NULL OR version.department IN scope.departments)
AND (version.ship_id IS NULL OR version.ship_id IN scope.allowed_ship_ids)
AND (version.project_id IS NULL OR version.project_id IN scope.allowed_project_ids)
```

Null ACL metadata is global for that dimension. Every non-null dimension
requires exact membership, and all present dimensions intersect. An empty
default scope can therefore retrieve a fully global `PUBLIC` document but no
department-, ship-, project-, or higher-clearance document. Scope ship/project
values must be canonical UUID text; canonical uppercase text is normalized,
while malformed and brace-wrapped values are ignored and cannot widen access.
Document-type, ship, and project filters are additional predicates in the same
query. An out-of-scope filter returns no result and never triggers an
unfiltered fallback.

Lexical matching combines `simple` PostgreSQL full-text search with escaped
literal case-insensitive substring matching backed by `pg_trgm`. The score is
exactly:

```text
0.7 * ts_rank_cd(simple_vector, plain_query, 32)
+ 0.3 * similarity(normalized_text, query)
```

Results order by score descending, source-update time descending, and chunk
UUID ascending. This final tie-break makes repeated retrieval deterministic.
Each lexical result sets `retrieval_score` and `lexical_score` to the same
finite non-negative score. The excerpt is an at-most-2,000-code-point window
centered on the first case-insensitive literal occurrence; a full-text-only
match starts at the beginning. Document/version/chunk IDs, title, section,
page, and source URI remain attached as provenance.

Task 013 does not add vector storage or embeddings (Task 014), hybrid merging
or reranking (Task 015), an API, Wiki search, Agent behavior, or answer
synthesis. The optional vector and rerank evidence fields remain unset.

## 5. Evidence

`KnowledgeEvidence` is an authorized pointer and excerpt, not a new source of
truth. It contains:

- document_id
- version_id
- chunk_id
- title
- section
- page
- source_uri
- excerpt
- retrieval_score
- lexical_score optional
- vector_score optional
- rerank_score optional

Original documents and immutable versions remain authoritative. Retrieved
text is untrusted source data and never an execution instruction.

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
