# Task 011: Structure-Aware Chunking Design

**Date:** 2026-08-19
**Status:** Approved design

## 1. Purpose

Task 011 converts the immutable parser output introduced by Task 010 into the
immutable `DocumentChunk` records introduced by Task 009. The chunker preserves
document structure whenever the parser provides it and uses deterministic
size-based splitting only for content that has no usable structure or for one
structural unit that exceeds the configured character budget.

The implementation is deliberately local and model-independent. It must not
read files, access object storage, connect to PostgreSQL, call a model or
tokenizer, perform OCR, or persist its result. Later ingestion orchestration may
compose parsing, chunking, and persistence without changing this contract.

## 2. Scope

Task 011 includes:

- a framework-independent `StructuralChunker` ingestion service;
- deterministic conversion from `ParsedDocument` to `DocumentChunk`;
- propagation of structural paths, the most specific section, and page numbers;
- heading-context prefixes for independently understandable chunks;
- structure-aware paragraph grouping;
- whole-table preservation with bounded row-group splitting;
- deterministic fallback splitting for unstructured or oversized content;
- public ingestion exports and knowledge-system documentation; and
- deterministic synthetic unit tests, including a class-rule-like hierarchy.

Task 011 does not include:

- parsing or parser changes unless a verified Task 010 defect blocks chunking;
- OCR or scanned-PDF handling, which belongs to Task 012;
- chunk persistence or schema changes;
- lexical, vector, hybrid, or reranking behavior;
- authorization or ACL duplication on chunks;
- tokenizers, embeddings, model SDKs, or external processes; or
- Task 012 or any later Task.

## 3. Architecture and dependency direction

The implementation lives in `services/ingestion/chunker.py` and depends only
on:

- `services.ingestion.parser` for `ParsedDocument`, `ParsedBlock`, and block
  kinds; and
- `packages.domain` for `DocumentChunk` and `document_chunk_id`.

The chunker returns domain records but has no repository dependency. ACL
metadata remains stored once on `DocumentVersion`; chunks inherit scope through
their immutable `version_id` relationship. The domain package remains unaware
of parsing and chunking.

The selected design uses one stateless service with private draft helpers. It
does not dispatch by file format. Format-specific knowledge ends at the Task
010 parser boundary; chunking consumes only the common semantic block model.

## 4. Public contract

```python
DEFAULT_MAX_CHARS = 2_000

class StructuralChunker:
    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS) -> None: ...

    def chunk(
        self,
        version_id: UUID,
        document: ParsedDocument,
    ) -> tuple[DocumentChunk, ...]: ...
```

`max_chars` is measured in Python Unicode code points after Task 010 text
normalization. It must be an exact positive integer; booleans are rejected.
The default is 2,000 characters. The implementation uses no tokenizer, so a
model or vendor change cannot alter chunk boundaries.

`chunk()` requires an exact `UUID` and an exact `ParsedDocument`. Invalid public
arguments raise fixed, non-sensitive `ValueError` messages:

- `max_chars must be a positive integer`;
- `version_id must be a UUID`; or
- `document must be a ParsedDocument`.

The output is a non-empty immutable tuple for every valid non-empty
`ParsedDocument`.

## 5. Determinism and identity

The chunker processes blocks in source order and assigns global contiguous
output ordinals `0..N-1`. Each final record uses the existing domain identity
function:

```python
chunk_id = document_chunk_id(version_id, structural_path, ordinal)
```

For the same exact `version_id`, `ParsedDocument`, and `max_chars`, the output
records and IDs are byte-for-byte/value-for-value equal across repeated runs.
No clock, randomness, process state, locale, database state, tokenizer, or
model is consulted.

Changing content within the same immutable version is outside the contract.
A real source change creates a different `DocumentVersion`, and therefore a
different `version_id` and Chunk IDs.

## 6. Structural context

### 6.1 Context key

The grouping context is the pair:

```text
(structural_path, page)
```

Adjacent non-table body blocks may be grouped only when both values are equal.
The chunker never crosses a page boundary or a structural-path boundary.

XLSX sheet names already occupy `structural_path` in Task 010, so they are
preserved without adding a sheet column to `DocumentChunk`.

### 6.2 Title and heading blocks

`TITLE` and `HEADING` blocks are context markers. Their text is already present
in their structural path, so they are not emitted as separate low-value chunks
when body content exists beneath the same path.

Every body or table chunk normally receives a textual context prefix:

```text
<path element 1> > <path element 2> > <path element 3>

<body text>
```

The full immutable tuple remains in `DocumentChunk.structural_path`. The
`section` field is the last, most specific path element, or `None` for an empty
path.

If a title or heading's entire subtree has no body or table content before the
parser leaves that subtree or the document ends, the chunker emits one
heading-only chunk so source content is not lost. Body under a descendant path
covers every ancestor marker; a chapter with populated subsections therefore
does not create a separate low-value chapter chunk.

If the complete textual prefix alone leaves no room for body content under
`max_chars`, the prefix is omitted from `normalized_text` for that chunk. The
full path and section remain in metadata. A heading-only value that itself
exceeds the budget uses the normal deterministic text splitter.

### 6.3 Page blocks

`PAGE` blocks retain their original one-based page number. Blank pages were
already omitted by Task 010, so page gaps remain gaps. Page text may split into
multiple chunks, but every resulting chunk keeps the same page number and no
chunk combines text from different pages.

## 7. Paragraph grouping and unstructured fallback

Adjacent non-table body blocks with the same context are accumulated in source
order. Paragraph units are separated by exactly two newline characters in
`normalized_text`. The chunker packs the maximum number of complete paragraph
units that fit under `max_chars`, including any textual path prefix.

An empty structural path with no page and no table semantics is an
unstructured region. The same deterministic packing algorithm acts as its
size-based fallback, and the resulting chunks keep `structural_path == ()`,
`page is None`, and `section is None`.

If one paragraph unit exceeds the available body budget, it is split in this
order:

1. newline boundaries;
2. other whitespace boundaries; and
3. exact Unicode code-point slices when no earlier boundary is available.

Splitting is stable, makes forward progress for every positive budget, and
does not add overlap. Leading and trailing split-boundary whitespace is
removed; internal normalized content order is preserved.

The fallback is local to the region that lacks structure. A Markdown preamble
may use an empty-path fallback while later headed sections continue to use
their structural paths.

## 8. Table behavior

Tables never merge with paragraphs or neighboring tables.

When the path prefix plus the complete canonical TSV table fits under
`max_chars`, the table produces exactly one chunk. The chunker must not split a
small table row-by-row.

When a table exceeds the budget:

1. the first row is treated as the header;
2. consecutive data rows are packed greedily into the largest row group that
   fits;
3. the header is repeated in every row-group chunk; and
4. row order is preserved exactly.

If the header plus one data row cannot fit, that data row uses deterministic
text splitting while retaining the same path, page, section, and source order.
If the header itself cannot fit, the canonical TSV text uses the generic text
splitter. This is the only fallback that may split within one table row.

Repeated headers are intentional retrieval context, not new source claims.
The persisted `DocumentChunk` schema has no table field, so the chunk text is
canonical TSV plus the optional structural prefix.

## 9. Draft-to-domain conversion

Private helpers may build immutable internal drafts containing:

- `structural_path`;
- body text;
- `page`; and
- derived `section`.

Only after all boundaries are decided does the service enumerate drafts and
construct `DocumentChunk` values. Each final `normalized_text` is non-blank and
does not exceed `max_chars`.

The service does not call `DocumentStore.add_chunks()`. The caller owns
persistence and transaction boundaries.

## 10. Safety and failure behavior

- Parsed text, headings, cells, and formulas remain untrusted data.
- The chunker performs no instruction interpretation, rendering, formula
  execution, external-resource access, or dynamic import.
- Unit tests make no network, model, filesystem, or database calls.
- There is no OCR fallback.
- The implementation does not expose parser-library exceptions because it
  receives only validated parser records.
- Exact character limits include textual prefixes and repeated table headers.
- Every split path must make forward progress; no loop may retry unchanged
  content.

## 11. Testing strategy

TDD begins with a class-rule-like structured document containing a title,
chapter, section, paragraphs, a table, and page-bearing content. The primary
test must fail because `StructuralChunker` is absent before implementation.

Focused tests cover:

1. repeated runs for one version produce identical chunks and Chunk IDs;
2. global ordinals are contiguous and use the existing deterministic ID
   function;
3. title/chapter/section paths and the leaf `section` propagate;
4. page numbers propagate and page boundaries never merge;
5. same-context paragraphs group while path/page changes flush;
6. an orphan heading is retained without producing duplicate heading chunks;
7. an empty-path preamble and TXT-like document use local unstructured
   fallback;
8. exact `max_chars` boundaries do not split;
9. oversized paragraphs split at newline, whitespace, then hard character
   boundaries without overlap;
10. a fitting table stays whole;
11. an oversized table uses the largest consecutive row groups and repeats
    the header;
12. an oversized header or individual row still makes bounded progress;
13. long structural prefixes never produce an over-budget chunk;
14. malformed configuration and public argument types receive fixed errors;
15. outputs are immutable `DocumentChunk` records; and
16. an AST import guard excludes persistence, network, model, tokenizer, OCR,
    retrieval, and Task 012 dependencies.

The relevant ingestion unit suite, document-domain unit suite, and existing
document-version integration tests run after focused GREEN. The complete
project quality gate runs before completion, followed by Ruff and mypy as
required by `AGENTS.md`.

## 12. Files

Expected Task 011 files:

- create `services/ingestion/chunker.py`;
- modify `services/ingestion/__init__.py`;
- create `tests/unit/ingestion/test_chunker.py`;
- modify `docs/03-knowledge-system.md`;
- add this design specification; and
- add the implementation plan produced after specification approval.

No migration, adapter, parser, repository, retrieval, OCR, or application file
is expected to change.

## 13. Acceptance mapping

| Task acceptance criterion | Design evidence |
|---|---|
| Same version produces same chunk IDs | Global deterministic ordinals plus existing UUIDv5 `document_chunk_id` |
| Sections/pages propagate into chunk metadata | Context-key grouping, leaf section derivation, and page-preserving splits |
| Tables are not split row-by-row unless size requires it | Whole-table first, then greedy consecutive row-group packing |
| Tests cover class-rule-like hierarchy | Primary synthetic Title -> Chapter -> Section fixture and focused assertions |

Task 011 stops after this behavior. Task 012 remains untouched.
