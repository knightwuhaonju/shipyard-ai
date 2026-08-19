# Structural Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert immutable Task 010 parser blocks into deterministic, structure-aware Task 009 `DocumentChunk` records without model, persistence, or tokenizer dependencies.

**Architecture:** Add one stateless `StructuralChunker` service that consumes the common `ParsedDocument` contract, creates private immutable drafts in source order, and materializes existing domain `DocumentChunk` values with global contiguous ordinals. Structural paths and pages define grouping boundaries; paragraph and table splitters enforce a configurable Unicode-character budget only when a structural unit cannot fit whole.

**Tech Stack:** Python 3.12, frozen/slotted dataclasses, existing ingestion parser contract, existing document domain model, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-19-structural-chunking-design.md`

## Global Constraints

- Implement Task 011 only; do not add OCR, retrieval, persistence orchestration, embeddings, tokenizers, model SDKs, migrations, or Task 012 behavior.
- The public API is `StructuralChunker(max_chars: int = 2_000).chunk(version_id: UUID, document: ParsedDocument) -> tuple[DocumentChunk, ...]`.
- `max_chars` counts Python Unicode code points in final `normalized_text`, including a textual path prefix and repeated table header.
- `max_chars` must be an exact positive integer; booleans are invalid.
- Input types are exact `UUID` and exact `ParsedDocument`; public validation messages are fixed and non-sensitive.
- Chunk ordinals are global contiguous integers `0..N-1`; IDs use the existing `document_chunk_id(version_id, structural_path, ordinal)` UUIDv5 function.
- Grouping never crosses a structural-path or page boundary.
- `section` is the last structural-path element, or `None` for an empty path.
- Title and heading markers are suppressed when their own subtree contains body/table content; a wholly empty subtree emits a heading-only Chunk.
- A complete table stays one Chunk when it fits. An oversized table uses the largest fitting consecutive data-row groups and repeats its first row as header.
- Unstructured and oversized text splits at newline, then other whitespace, then exact code-point boundaries, with no overlap.
- Every final Chunk is non-blank and at most `max_chars` characters.
- The service is pure and framework-independent: no database, repository, filesystem, network, model, OCR, external process, clock, randomness, or authorization dependency.
- Tests use only deterministic synthetic shipyard/class-rule content.

---

### Task 1: Core Structured Chunker and Deterministic Identity

**Files:**
- Create: `services/ingestion/chunker.py`
- Create: `tests/unit/ingestion/test_chunker.py`

**Interfaces:**
- Consumes: `ParsedDocument`, `ParsedBlock`, `ParsedBlockKind`, `DocumentChunk`, and `document_chunk_id`.
- Produces: `DEFAULT_MAX_CHARS: int` and `StructuralChunker.chunk(version_id: UUID, document: ParsedDocument) -> tuple[DocumentChunk, ...]`.
- Establishes private `_ChunkDraft`, `_Marker`, `_context_prefix`, `_body_budget`, `_decorate`, and `_materialize` helpers used by later tasks.

- [ ] **Step 1: Create the primary class-rule hierarchy test and helpers**

Create `tests/unit/ingestion/test_chunker.py` with exact UUIDs and builders that always construct valid Task 010 records:

```python
from uuid import UUID

from packages.domain import DocumentChunk, document_chunk_id
from services.ingestion.chunker import StructuralChunker
from services.ingestion.parser import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    render_table,
)

VERSION_ID = UUID("91000000-0000-0000-0000-000000000001")


def _document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(format=DocumentFormat.MARKDOWN, blocks=blocks)


def test_class_rule_hierarchy_produces_deterministic_structural_chunks() -> None:
    table = (("Item", "Requirement"), ("Pump", "Two independent units"))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TITLE,
            text="Synthetic Class Rules",
            structural_path=("Synthetic Class Rules",),
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.HEADING,
            text="Chapter 3",
            structural_path=("Synthetic Class Rules", "Chapter 3"),
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.HEADING,
            text="Fire Pumps",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=3,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Each synthetic vessel has an independently driven fire pump.",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=4,
            kind=ParsedBlockKind.PARAGRAPH,
            text="The second synthetic pump remains available after one failure.",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=5,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
            table=table,
        ),
    )

    first = StructuralChunker().chunk(VERSION_ID, document)
    second = StructuralChunker().chunk(VERSION_ID, document)

    assert first == second
    assert len(first) == 2
    assert [chunk.ordinal for chunk in first] == [0, 1]
    assert all(type(chunk) is DocumentChunk for chunk in first)
    assert all(
        chunk.chunk_id
        == document_chunk_id(VERSION_ID, chunk.structural_path, chunk.ordinal)
        for chunk in first
    )
    assert first[0].structural_path == (
        "Synthetic Class Rules",
        "Chapter 3",
        "Fire Pumps",
    )
    assert first[0].section == "Fire Pumps"
    assert first[0].normalized_text.startswith(
        "Synthetic Class Rules > Chapter 3 > Fire Pumps\n\n"
    )
    assert "one failure" in first[0].normalized_text
    assert first[1].normalized_text.endswith(render_table(table))
```

- [ ] **Step 2: Run the primary node and verify RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_chunker.py::test_class_rule_hierarchy_produces_deterministic_structural_chunks \
  -v
```

Expected: collection fails because `services.ingestion.chunker` does not exist. Confirm no Task 011 production file exists before this run.

- [ ] **Step 3: Implement configuration, private drafts, context decoration, and materialization**

Create `services/ingestion/chunker.py` with these exact public and private record shapes:

```python
from dataclasses import dataclass
from uuid import UUID

from packages.domain import DocumentChunk, document_chunk_id
from services.ingestion.parser import ParsedBlock, ParsedBlockKind, ParsedDocument

DEFAULT_MAX_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    structural_path: tuple[str, ...]
    normalized_text: str
    page: int | None


@dataclass(frozen=True, slots=True)
class _Marker:
    structural_path: tuple[str, ...]
    text: str
    page: int | None


class StructuralChunker:
    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        if type(max_chars) is not int or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")
        self._max_chars = max_chars

    def chunk(
        self, version_id: UUID, document: ParsedDocument
    ) -> tuple[DocumentChunk, ...]:
        if type(version_id) is not UUID:
            raise ValueError("version_id must be a UUID")
        if type(document) is not ParsedDocument:
            raise ValueError("document must be a ParsedDocument")
        drafts = _structured_drafts(document.blocks, self._max_chars)
        return _materialize(version_id, drafts)
```

Implement these exact invariants:

- `_context_prefix(path)` joins elements with `" > "`;
- `_body_budget(path, max_chars)` returns `(prefix_or_empty, body_budget)`, using `prefix + "\n\n"` only when at least one body character remains;
- `_decorate(path, body, max_chars)` returns either `prefix + "\n\n" + body` or body alone and asserts its result is within the limit;
- `_materialize` enumerates drafts globally, derives `section` from `path[-1]`, and constructs each deterministic domain record;
- a private mutable list buffers consecutive paragraph texts for one `(path, page)` context and flushes before tables or context changes;
- a fitting table is one draft and never joins paragraph text; and
- marker paths are delayed until their subtree outcome is known.

Use a prefix test (`candidate_path[:len(marker_path)] == marker_path`) to decide whether an incoming body/table is inside a marker subtree. Body/table content removes every pending ancestor marker it covers. Before entering a path outside a pending marker subtree, flush that uncovered marker as a heading-only draft in source order. At end of input, flush remaining uncovered markers. A populated child section therefore covers its title/chapter ancestors.

For Task 1, paragraph packing may assume the complete same-context paragraph group fits. Task 2 replaces that narrow helper with bounded packing. For Task 1, a table may assume the complete decorated TSV fits. Task 3 adds oversized-table splitting.

- [ ] **Step 4: Run the primary node and verify GREEN**

Run the same primary command. Expected: `1 passed`.

- [ ] **Step 5: Add focused deterministic-identity and marker tests**

Add tests that assert:

- a different `version_id` changes every Chunk ID while preserving text and metadata;
- a wholly empty sibling heading subtree emits exactly one heading-only Chunk;
- title and chapter markers with populated descendants do not emit standalone Chunks;
- two paragraph regions with different structural paths never merge; and
- all ordinals remain global and contiguous across paragraph, orphan-heading, and table drafts.

Use only synthetic headings such as `Chapter 4`, `Steering Gear`, and `Synthetic Requirement`.

- [ ] **Step 6: Run Task 1 focused tests and static checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_chunker.py -k "hierarchy or identity or marker or ordinal" -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
```

Expected: all selected tests and both static checks pass.

- [ ] **Step 7: Commit the core structured slice**

```bash
git add services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
git commit -m "feat: add deterministic structural chunker"
```

---

### Task 2: Bounded Paragraph Fallback, Page Propagation, and Public Validation

**Files:**
- Modify: `services/ingestion/chunker.py`
- Modify: `tests/unit/ingestion/test_chunker.py`

**Interfaces:**
- Consumes: Task 1 `StructuralChunker`, `_ChunkDraft`, prefix helpers, and materialization.
- Produces: bounded `_split_text`, `_pack_paragraphs`, and page-preserving paragraph/page behavior for Task 3 and final public use.

- [ ] **Step 1: Add RED tests for local fallback and page boundaries**

Add a test with a small computed budget rather than a magic expected split:

```python
def test_unstructured_fallback_splits_deterministically_without_overlap() -> None:
    first = "Synthetic pump requirement alpha."
    second = "Synthetic pump requirement beta."
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text=first,
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.PARAGRAPH,
            text=second,
        ),
    )

    chunks = StructuralChunker(max_chars=len(first)).chunk(VERSION_ID, document)

    assert [chunk.structural_path for chunk in chunks] == [(), ()]
    assert [chunk.section for chunk in chunks] == [None, None]
    actual = "".join(
        "".join(chunk.normalized_text.split()) for chunk in chunks
    )
    expected = "".join((first + second).split())
    assert actual == expected
    assert all(len(chunk.normalized_text) <= len(first) for chunk in chunks)
```

Add one PDF-format document with page blocks numbered 1 and 3; use text that forces page 1 into two Chunks. Assert pages are `[1, 1, 3]` and no normalized text crosses pages.

Run these new nodes. Expected: at least the unstructured split fails because Task 1 still assumes a complete group fits.

- [ ] **Step 2: Implement the deterministic text splitter**

Add:

```python
def _split_text(text: str, budget: int) -> tuple[str, ...]: ...
```

The implementation advances an offset over the original text and selects at
most `budget` code points from the current bounded window. Within that window
it prefers the last `"\n"`; otherwise the last Unicode whitespace; otherwise
it cuts at exactly `budget`. Strip only the chosen fragment's outer whitespace
and consume the chosen delimiter so every iteration makes forward progress.
Do not repeatedly copy the complete remaining suffix, use tokenization, apply
regex backtracking over the complete document, or add overlap.

If the input is already within budget, return it as one element without changing internal whitespace. Empty fragments are skipped, and a non-blank input must produce at least one fragment.

- [ ] **Step 3: Implement bounded paragraph packing and page isolation**

Add:

```python
def _pack_paragraphs(
    structural_path: tuple[str, ...],
    page: int | None,
    paragraphs: tuple[str, ...],
    max_chars: int,
) -> tuple[_ChunkDraft, ...]: ...
```

Compute the usable body budget with `_body_budget`. Greedily append a complete paragraph using `"\n\n"` when the decorated candidate fits. Flush the current body before an oversized paragraph. Split an oversized paragraph with `_split_text(body_budget)`, decorating each fragment separately. Never group across `(structural_path, page)`.

Use the same helper for `PAGE` text; its non-null `page` is part of the context and propagates to every resulting draft.

- [ ] **Step 4: Add exact-boundary, long-prefix, and split-order tests**

Add exact tests for:

- a body whose decorated length equals `max_chars` stays one Chunk;
- one extra code point creates two Chunks;
- an oversized paragraph chooses newline before whitespace and whitespace before hard slicing;
- a single word longer than `max_chars` is cut into exact code-point slices;
- a structural prefix that leaves no body room is omitted from text while the full path and leaf section remain in metadata;
- a heading-only path longer than the budget splits into bounded Chunks with the same path/section;
- a Markdown-like empty-path preamble uses fallback while later headed content uses its non-empty path; and
- no Chunk contains duplicated overlap text.

- [ ] **Step 5: Add exact public validation tests**

Use `typing.cast(Any, ...)` to pass invalid types and assert exact messages:

```python
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2000"])
def test_chunker_rejects_invalid_character_budget(value: object) -> None:
    with pytest.raises(ValueError, match="^max_chars must be a positive integer$"):
        StructuralChunker(max_chars=cast(Any, value))
```

Also assert a string `version_id` raises `version_id must be a UUID`, and a `ParsedDocument` subclass instance raises `document must be a ParsedDocument`. Verify valid output is a tuple of exact frozen `DocumentChunk` values.

- [ ] **Step 6: Run Task 2 focused and relevant unit suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_chunker.py -k "fallback or page or boundary or prefix or validation" -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion tests/unit/domain/test_documents.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
```

Expected: all pass with no skipped Task 011 test.

- [ ] **Step 7: Commit the bounded text slice**

```bash
git add services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
git commit -m "feat: bound structural paragraph chunks"
```

---

### Task 3: Whole-Table Preservation and Oversized Row Groups

**Files:**
- Modify: `services/ingestion/chunker.py`
- Modify: `tests/unit/ingestion/test_chunker.py`

**Interfaces:**
- Consumes: Task 1 prefix/draft/materialization helpers and Task 2 `_split_text`.
- Produces: deterministic `_table_drafts(block: ParsedBlock, max_chars: int) -> tuple[_ChunkDraft, ...]`.

- [ ] **Step 1: Add a fitting-table RED/guard test**

Create a table with one header and three data rows. Set `max_chars` to the exact decorated full-table length and assert the result has exactly one Chunk whose text ends with the original `render_table(table)`. This test is a guard for Task 1 whole-table behavior and must pass before table-splitting changes.

- [ ] **Step 2: Add the primary oversized-table RED test**

Build an empty-path table so the budget calculation is exact:

```python
def test_oversized_table_uses_largest_consecutive_row_groups() -> None:
    header = ("Item", "Requirement")
    row_a = ("A", "Independent synthetic pump")
    row_b = ("B", "Emergency synthetic supply")
    row_c = ("C", "Remote synthetic alarm")
    table = (header, row_a, row_b, row_c)
    two_row_budget = len(render_table((header, row_a, row_b)))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            table=table,
        )
    )

    chunks = StructuralChunker(max_chars=two_row_budget).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        render_table((header, row_a, row_b)),
        render_table((header, row_c)),
    ]
```

Run this node. Expected: FAIL because the complete table exceeds the Task 1 narrow path.

- [ ] **Step 3: Implement greedy table row-group drafts**

Implement:

```python
def _table_drafts(
    block: ParsedBlock, max_chars: int
) -> tuple[_ChunkDraft, ...]: ...
```

Require `block.table` through the existing validated `ParsedBlock` contract. First try the complete canonical `block.text`. If decorated text fits, return one draft unchanged.

For an oversized table:

- use `block.table[0]` as the header;
- canonicalize the header and each remaining row once;
- iterate remaining rows in order while tracking the candidate rendered length
  incrementally;
- retain the largest candidate whose decorated result fits;
- flush and render the accumulated group before adding the first row that
  would exceed the budget; and
- retry that row as the first row of the next group.

When `header + row` cannot fit, flush any prior group. If the bounded canonical
header is non-blank, emit it as a standalone context Chunk immediately before
the canonical row fragments, repeating it for every individually oversized
data row. An all-whitespace or empty header emits no blank context Chunk. Pass
the canonical row text through `_split_text` using the available body budget,
preserving path, page, section derivation, and global output order. Preserve
canonical all-empty rows when they fit in a non-blank group; omit only an
all-empty fallback row that could produce nothing except a forbidden
whitespace-only `DocumentChunk`. When the header itself cannot fit, split
`block.text` generically rather than looping on an impossible row group.

- [ ] **Step 4: Add table boundary and safety tests**

Add tests that verify:

- exact full-table boundary stays whole;
- one extra row triggers splitting;
- every row appears exactly once and in order, excluding intentional repeated headers;
- each row-group Chunk repeats the identical header;
- a single oversized data row makes bounded progress and every Chunk is within `max_chars`;
- an oversized header makes bounded progress through generic TSV splitting;
- a one-row table remains one Chunk when it fits and splits deterministically when it does not;
- a table never merges with adjacent paragraphs or a neighboring table; and
- a path prefix and page are preserved on every table fragment.

- [ ] **Step 5: Run complete chunker and ingestion unit suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_chunker.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion tests/unit/domain/test_documents.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
```

Expected: all pass.

- [ ] **Step 6: Commit the table slice**

```bash
git add services/ingestion/chunker.py tests/unit/ingestion/test_chunker.py
git commit -m "feat: preserve structural table regions"
```

---

### Task 4: Public Surface, Documentation, Architecture Guard, and Complete Gate

**Files:**
- Modify: `services/ingestion/__init__.py`
- Modify: `tests/unit/ingestion/test_chunker.py`
- Modify: `docs/03-knowledge-system.md`
- Modify only for a verified Task 011 defect: `services/ingestion/chunker.py`

**Interfaces:**
- Consumes: complete Task 1-3 `StructuralChunker` behavior.
- Produces: public ingestion exports, documented chunking contract, architecture regression coverage, and final Definition-of-Done evidence.

- [ ] **Step 1: Add public import and architecture-boundary RED tests**

Import `DEFAULT_MAX_CHARS` and `StructuralChunker` from `services.ingestion`, not the implementation module, and assert the public `__all__` contains both without losing any Task 010/document-store names.

Use `ast` to inspect `services/ingestion/chunker.py`. Permit only non-relative import roots used by the final implementation from this exact set:

```python
{"dataclasses", "packages", "services", "uuid"}
```

Assert these roots or qualified imports are absent: `sqlalchemy`, `requests`, `httpx`, `urllib`, `socket`, `pathlib`, `os`, `subprocess`, `tiktoken`, `transformers`, `pypdf`, `docx`, `openpyxl`, `adapters.ocr`, `services.retrieval`, and model SDK roots. Also assert the source contains no `DocumentStore` or repository import.

Run the public import node before editing `services/ingestion/__init__.py`. Expected: FAIL because Task 011 names are not exported.

- [ ] **Step 2: Export the public chunker contract**

Modify `services/ingestion/__init__.py` to import and add to `__all__`:

```python
from services.ingestion.chunker import DEFAULT_MAX_CHARS, StructuralChunker
```

Keep the existing exact parser and document-store exports unchanged.

- [ ] **Step 3: Document the Task 011 contract**

Extend `docs/03-knowledge-system.md` section `## 3. Chunking` with:

- the pure `ParsedDocument -> tuple[DocumentChunk, ...]` service boundary;
- the 2,000 Unicode-character default and explicit configurability;
- heading-path prefixes, leaf `section`, page propagation, and global deterministic ordinals/IDs;
- same-context paragraph grouping and local unstructured fallback;
- whole-table-first behavior and repeated-header row groups only when oversized;
- no overlap, tokenizer, model, OCR, network, filesystem, persistence, or authorization behavior; and
- Task 012 remains the owner of optional OCR.

Do not document retrieval or OCR behavior as implemented.

- [ ] **Step 4: Run focused acceptance and relevant integration suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_chunker.py \
  tests/unit/ingestion/test_parsers.py \
  tests/unit/domain/test_documents.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_document_versions.py -v
```

Expected: zero Task 011 failures/skips, and the existing domain/persistence contract accepts generated `DocumentChunk` values without a schema change.

- [ ] **Step 5: Run the complete project gate**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
git diff --check c4b581b...HEAD
git diff --name-only c4b581b...HEAD
```

Expected:

- all tests pass;
- Ruff prints `All checks passed!`;
- mypy reports no issues;
- pip reports `No broken requirements found.`;
- changed files are restricted to the approved Task 011 spec/plan, chunker, ingestion exports, unit tests, and knowledge-system documentation; and
- no migration, OCR, adapter, retrieval, model, repository, or Task 012 file appears.

- [ ] **Step 6: Record acceptance evidence explicitly**

The final report must map evidence to all four Task acceptance criteria:

1. same version/document/config produces equal records and identical UUIDv5 Chunk IDs;
2. structural paths, leaf sections, and original pages propagate through every split;
3. a fitting table stays whole and oversized tables use maximal consecutive row groups with repeated headers; and
4. the class-rule hierarchy test covers title, chapter, section, paragraphs, and table content.

Also report public validation behavior, architecture import guard, no real data/secrets, and no Task 012 work.

- [ ] **Step 7: Commit the public/documentation slice**

```bash
git add services/ingestion/__init__.py tests/unit/ingestion/test_chunker.py \
  docs/03-knowledge-system.md
git commit -m "docs: publish structural chunking contract"
```

- [ ] **Step 8: Request final independent review and stop before Task 012**

Request a read-only spec/code/security review across `c4b581b...HEAD` against
`AGENTS.md`, `tasks/011-structural-chunking.md`, the approved specification,
and this plan. Resolve every verified P0/P1/P2 finding with focused TDD and
rerun the complete gate after material fixes. Report P3 findings as known
limitations. Do not merge, push, or begin Task 012 without explicit user
choice.
