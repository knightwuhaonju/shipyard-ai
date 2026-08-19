# Task 010 Parser Adapters Design

**Date:** 2026-08-19
**Status:** Approved for implementation planning
**Task:** `tasks/010-parser-adapters.md`

## 1. Scope

Task 010 introduces one framework-independent parsing contract and local
adapters for:

- UTF-8 text;
- Markdown;
- DOCX;
- XLSX; and
- text-layer PDF.

Every adapter returns the same immutable, ordered representation. The output
preserves the structural information needed by Task 011 without creating
chunks in Task 010.

Task 010 does not:

- discover files or infer authorization;
- read arbitrary paths supplied by an Agent;
- persist documents, versions, or chunks;
- calculate Chunk IDs;
- perform OCR;
- execute macros, formulas, scripts, HTML, or external links;
- implement retrieval, embeddings, or an ingestion job runner; or
- begin Task 011 or Task 012.

## 2. Architecture constraints

The ingestion service owns the parser port and its public data contracts. The
format adapters depend on that port:

```text
future ingestion orchestration
        |
        v
services/ingestion/parser.py       common immutable contract
        ^
        |
adapters/parsers/*.py              replaceable local implementations
```

The allowed dependency direction is therefore adapters -> service port. The
domain package remains independent of parser libraries, file formats,
frameworks, and storage.

Parser inputs are bytes. An adapter never opens an arbitrary caller-provided
filesystem path. File discovery and object-store access remain separate
boundaries. The original immutable DocumentVersion remains the source of
truth; parsed output is a reproducible derived artifact.

All document contents are untrusted data. A heading, formula, hyperlink,
embedded instruction, or PDF text object can contribute facts to later
retrieval but can never become executable instruction.

## 3. Chosen approach

Use a small shared contract with format-specific pure Python libraries:

- standard library for TXT and the supported Markdown subset;
- `python-docx` for DOCX;
- `openpyxl` for XLSX; and
- `pypdf` for PDF text-layer extraction.

This is preferred to hand-written OOXML/PDF parsing because the latter would
duplicate complex format behavior. It is preferred to LibreOffice, Apache
Tika, or another external process because V1 does not need a separate parser
service, Java runtime, or office-conversion sandbox.

The libraries stay behind adapter boundaries. A future replacement does not
change the service contract or Task 011.

## 4. Public parser contract

Create `services/ingestion/parser.py` with these public types.

### 4.1 Enums

```python
class DocumentFormat(StrEnum):
    TXT = "txt"
    MARKDOWN = "markdown"
    DOCX = "docx"
    XLSX = "xlsx"
    PDF = "pdf"


class ParsedBlockKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    PAGE = "page"


class ParserErrorCode(StrEnum):
    INVALID_DOCUMENT = "invalid_document"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    ENCRYPTED_DOCUMENT = "encrypted_document"
    RESOURCE_LIMIT = "resource_limit"
    EMPTY_DOCUMENT = "empty_document"
    OCR_REQUIRED = "ocr_required"
```

Format selection is explicit. Task 010 does not infer a parser by trusting a
user-controlled filename, extension, or MIME header.

### 4.2 Immutable records

```python
TableCells = tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedBlock:
    ordinal: int
    kind: ParsedBlockKind
    text: str
    structural_path: tuple[str, ...] = ()
    page: int | None = None
    sheet: str | None = None
    table: TableCells | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedDocument:
    format: DocumentFormat
    blocks: tuple[ParsedBlock, ...]
```

The records validate these invariants:

- ordinals are real non-negative integers, not booleans;
- `ParsedDocument` ordinals are exactly `0..len(blocks)-1`;
- `kind`, `format`, page, sheet, path, and table values have exact types;
- text, path elements, and provided sheet names are non-blank;
- page numbers are positive integers and reject booleans;
- PAGE blocks require `page` and cannot carry a table;
- TABLE blocks require a non-empty rectangular table and cannot carry a page;
- non-TABLE blocks cannot carry table cells;
- only XLSX blocks carry `sheet`;
- table block text equals the canonical rendering of its cells; and
- a ParsedDocument has at least one block.

`render_table(cells)` is a public deterministic helper used by adapters and
Task 011. Table cell normalization removes leading/trailing whitespace,
normalizes line endings, and collapses internal horizontal/newline whitespace
to one ASCII space. The canonical rendering joins cells with `"\t"` and rows
with `"\n"`. Empty cells are preserved, and trailing all-empty rows and
columns are removed before construction.

### 4.3 Port

```python
class Parser(Protocol):
    @property
    def format(self) -> DocumentFormat: ...

    def parse(self, content: bytes) -> ParsedDocument: ...
```

The protocol deliberately has no path, credentials, authorization scope,
storage handle, OCR adapter, or persistence dependency.

### 4.4 Typed errors

`ParserError` extends `RuntimeError` and carries a public `code` field of type
`ParserErrorCode`. It uses one fixed public message for each code:

| Code | Message |
|---|---|
| `INVALID_DOCUMENT` | `document cannot be parsed` |
| `UNSUPPORTED_ENCODING` | `document text encoding is unsupported` |
| `ENCRYPTED_DOCUMENT` | `encrypted documents are unsupported` |
| `RESOURCE_LIMIT` | `document exceeds parser resource limits` |
| `EMPTY_DOCUMENT` | `document contains no parseable content` |
| `OCR_REQUIRED` | `PDF has no extractable text layer` |

Messages never contain input text, a filename, a password, a cell value, a
library exception, or other caller-controlled data. Adapters translate only
expected parsing/library errors. Programmer errors are not swallowed.

## 5. Normalization and resource policy

Shared helpers in the service contract provide deterministic validation and
normalization without changing technical meaning:

- accept only `bytes`;
- enforce `MAX_SOURCE_BYTES = 25 * 1024 * 1024` before library parsing;
- reject NUL characters in text inputs and parsed text;
- normalize CRLF and CR to LF;
- trim leading/trailing whitespace around a block;
- remove trailing whitespace from individual lines;
- preserve Unicode code points and do not apply NFKC/NFKD normalization;
- enforce `MAX_BLOCKS = 10_000`;
- enforce `MAX_BLOCK_CHARS = 1_000_000`;
- enforce `MAX_TOTAL_TEXT_CHARS = 5_000_000`;
- enforce `MAX_TABLE_ROWS = 10_000`;
- enforce `MAX_TABLE_COLUMNS = 256`;
- enforce `MAX_TABLE_CELLS = 100_000`; and
- enforce `MAX_ARCHIVE_ENTRIES = 10_000`,
  `MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024`, and
  `MAX_ARCHIVE_COMPRESSION_RATIO = 100` for OOXML containers; and
- enforce `MAX_PDF_PAGES = 2_000` and
  `MAX_PDF_PAGE_STREAM_BYTES = 10 * 1024 * 1024`.

Cross-format output validation runs before an adapter returns. Any limit
failure becomes `ParserError(RESOURCE_LIMIT)`.

Before `python-docx` or `openpyxl` receives content, a shared OOXML preflight
opens the bytes as a ZIP container without extracting files. It rejects an
invalid archive, duplicate member names, absolute paths, parent traversal,
too many members, excessive declared uncompressed bytes, or an excessive
per-member compression ratio. Directory entries are ignored when calculating
the ratio. The libraries still read from `BytesIO`; no archive member is
written to the filesystem.

The limits are module constants for this Task, not environment configuration.
Making them pilot-configurable can be added with observed workload evidence;
it is not required to define the parser contract.

## 6. Adapter behavior

### 6.1 TXT

`TxtParser` decodes `utf-8-sig`, so an optional UTF-8 BOM is accepted. Any
invalid byte sequence produces `UNSUPPORTED_ENCODING`; no locale-dependent or
fallback encoding is attempted.

After newline normalization, one or more blank lines separate paragraphs.
Each non-blank paragraph becomes a PARAGRAPH block with an empty structural
path. An all-blank document produces `EMPTY_DOCUMENT`.

### 6.2 Markdown

`MarkdownParser` decodes identically to TXT and implements a deterministic,
non-rendering subset sufficient for shipyard knowledge documents:

- ATX headings (`#` through `######`);
- Setext level-one and level-two headings;
- paragraphs separated by blank lines; and
- GitHub-style pipe tables with a delimiter row.

Heading blocks are HEADING blocks. A heading path contains the active heading
stack including the heading itself. Following paragraphs and tables carry the
same path. A shallower heading replaces deeper path elements.

A recognized Markdown table remains one TABLE block with rectangular cell
data. Raw HTML, fenced code, links, and document-like instructions are treated
as literal text; they are never rendered, fetched, or executed. Task 010 does
not attempt complete CommonMark conformance.

### 6.3 DOCX

`DocxParser` opens a `BytesIO` stream through `python-docx` and iterates
top-level paragraphs and tables in document order.

- a paragraph styled `Title` becomes TITLE;
- a paragraph styled `Heading 1` through `Heading 9` becomes HEADING and
  updates the heading path;
- other non-blank paragraphs become PARAGRAPH; and
- each top-level table becomes one TABLE block.

The Title is a root path element. Subsequent Heading levels extend or replace
the active path. Blank paragraphs and empty tables are omitted. If no blocks
remain, the result is `EMPTY_DOCUMENT`.

Headers, footers, comments, tracked-change-only content, text boxes, images,
and nested tables are not extracted in Task 010. They remain in the immutable
source document and can be added through a later adapter enhancement without
changing the public representation.

DOCX relationships are not followed and no embedded object is executed.

### 6.4 XLSX

`XlsxParser` uses `openpyxl.load_workbook` with:

```python
read_only=True
data_only=False
keep_links=False
keep_vba=False
```

The workbook is always explicitly closed. Read-only iteration and parser
limits bound processing. The adapter does not calculate formulas: a formula
cell is returned as its literal formula string. External workbook links are
not retained or fetched, macros are not preserved, and charts/images are not
parsed.

Each non-empty worksheet becomes exactly one TABLE block. `sheet` contains the
worksheet title and `structural_path == (sheet,)`. Cell values are converted
deterministically:

- strings remain strings after table-cell normalization;
- booleans become `TRUE` or `FALSE`;
- `date`, `time`, and `datetime` values use ISO format;
- numeric values use their Python string representation; and
- `None` becomes an empty cell.

All-empty trailing rows and columns are trimmed; interior empty cells remain.
An all-empty workbook produces `EMPTY_DOCUMENT`.

### 6.5 PDF

`PdfParser` uses `pypdf.PdfReader` against a `BytesIO` stream. It does not
render pages and has no OCR dependency.

- encrypted PDFs produce `ENCRYPTED_DOCUMENT`; Task 010 does not try an empty
  password;
- page count and decoded page content streams are checked against limits;
- each page with non-blank extracted text becomes one PAGE block;
- page numbers are one-based and preserve gaps from pages without text; and
- if every page lacks extractable text, the adapter returns `OCR_REQUIRED`.

An empty-text result is deliberately conservative: it means no usable text
layer exists for this adapter, not that OCR has already classified the page.
Task 012 owns optional scanned-PDF detection and OCR orchestration.

PDF does not provide a reliable semantic layer for headings, paragraphs, or
tables. Task 010 therefore preserves page boundaries and extracted text rather
than inventing unsupported structure.

## 7. Dependencies and packaging

Add runtime compatibility ranges to `pyproject.toml`:

```text
python-docx >= 1.2, < 2.0
openpyxl >= 3.1, < 4.0
pypdf >= 6.0, < 7.0
defusedxml >= 0.7, < 1.0
```

Regenerate `requirements-dev.lock` intentionally with exact direct and
transitive versions. The expected new transitive packages include `lxml` and
`et_xmlfile`. The lock must remain installable using the existing
`make install-dev` no-dependency installation sequence, and `pip check` must
pass.

No OCR, HTML renderer, Java service, LibreOffice, model SDK, network client,
or native PDF renderer is added.

## 8. Files

Create:

- `services/ingestion/parser.py`
- `adapters/parsers/__init__.py`
- `adapters/parsers/_common.py`
- `adapters/parsers/text.py`
- `adapters/parsers/markdown.py`
- `adapters/parsers/docx.py`
- `adapters/parsers/xlsx.py`
- `adapters/parsers/pdf.py`
- `tests/fixtures/parser_documents.py`
- `tests/unit/ingestion/test_parsers.py`

Modify:

- `services/ingestion/__init__.py`
- `pyproject.toml`
- `requirements-dev.lock`
- `docs/03-knowledge-system.md`

The separate fixture-builder module is a deliberate refinement of the Task's
suggested paths: it keeps deterministic binary fixture construction out of the
behavior tests and contains only synthetic test data.

## 9. TDD and verification

### 9.1 Contract tests

Begin with failing tests for the missing public types and Parser Protocol.
Cover immutability, contiguous ordinals, block-kind invariants, canonical
tables, fixed typed errors, byte/size validation, and public exports.

### 9.2 Adapter tests

Use deterministic synthetic fixture builders:

- TXT with UTF-8 BOM, Unicode shipyard text, and multiple paragraphs;
- Markdown with heading hierarchy, paragraphs, and one complete table;
- DOCX with Title, two heading levels, paragraph, and table in source order;
- XLSX with two sheets, formulas, dates, booleans, and interior empty cells;
- minimal text-layer PDF with two numbered pages; and
- blank/encrypted/malformed/oversized variants for failure paths.

The fixture builders write to `BytesIO`; tests do not need real customer files
or network access. The text-layer PDF builder may generate a minimal PDF byte
sequence directly so no report-generation dependency is added.

Tests assert:

- every adapter satisfies the Parser Protocol and returns ParsedDocument;
- output block order and ordinals are deterministic;
- structural paths, page numbers, sheet names, and complete tables survive;
- XLSX formulas remain literal and are not executed;
- malformed inputs return the correct code and fixed safe message;
- an empty-text PDF returns OCR_REQUIRED and no OCR package is imported;
- resource limits fail before unbounded output is returned; and
- adapter modules do not import OCR, retrieval, persistence, model, or network
  packages.

### 9.3 Gates

Run, in order:

```bash
python -m pytest tests/unit/ingestion/test_parsers.py -v
python -m pytest tests/unit/ingestion -v
python -m ruff check .
python -m mypy .
make check
```

Because Task 010 adds no database schema, no migration is created. Existing
PostgreSQL integration tests still run as part of the complete gate against
the isolated test database.

## 10. Acceptance mapping

| Task acceptance criterion | Design evidence |
|---|---|
| All parsers return a common structured representation | Parser Protocol, ParsedDocument, ParsedBlock, canonical tables |
| Parser errors are typed | ParserErrorCode and ParserError fixed-message contract |
| No OCR is silently invoked | PDF returns OCR_REQUIRED and has no OCR dependency |
| Synthetic fixtures cover every format | deterministic fixture builders and per-format unit tests |

## 11. Known limitations

- Markdown support is a documented deterministic subset rather than a complete
  CommonMark renderer.
- DOCX extraction is limited to top-level body paragraphs and tables.
- XLSX charts, images, comments, macros, and external-link contents are not
  parsed.
- PDF structure is page-level because PDF text streams have no dependable
  semantic hierarchy.
- Password-protected documents are rejected rather than decrypted.
- Task 010 does not persist parsed artifacts or expose an API.

These limitations are explicit failures or preserved source content; none are
silently replaced by guessed text or OCR.
