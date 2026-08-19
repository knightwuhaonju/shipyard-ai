# Parser Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement one immutable parser contract and safe local adapters for TXT, Markdown, DOCX, XLSX, and text-layer PDF.

**Architecture:** `services/ingestion/parser.py` owns the framework-independent port, immutable parsed records, validation, normalization, and typed errors. `adapters/parsers` contains replaceable byte-input implementations; no adapter reads an arbitrary path, performs OCR, executes document content, persists records, or starts Task 011.

**Tech Stack:** Python 3.12, dataclasses, `python-docx`, `openpyxl`, `pypdf`, `defusedxml`, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-19-parser-adapters-design.md`

## Global Constraints

- Implement Task 010 only; do not create chunks, invoke OCR, persist parsed output, implement retrieval, or begin Task 011/012.
- Parser inputs are `bytes`; no public parser API accepts a path, URL, storage handle, credentials, or user identity.
- Dependency direction is adapters -> `services.ingestion.parser`; `packages.domain` remains parser-library independent.
- All parsed content is untrusted data; never execute macros, formulas, scripts, HTML, hyperlinks, or external workbook links.
- Every adapter returns the same frozen `ParsedDocument` / `ParsedBlock` representation with exact contiguous ordinals.
- PDF extraction is text-layer only. An all-empty extraction returns `ParserErrorCode.OCR_REQUIRED`; no OCR dependency or call is permitted.
- Parser errors use the exact fixed messages from the approved spec and never include caller content or library exception text.
- Preserve Unicode code points; normalize newlines and boundary whitespace only. Do not apply NFKC/NFKD.
- Enforce exact limits from the spec: 25 MiB source, 10,000 blocks, 1,000,000 chars per block, 5,000,000 total chars, 10,000 table rows, 256 columns, 100,000 cells, 10,000 archive entries, 100 MiB declared archive output, archive ratio 100, 2,000 PDF pages, and 10 MiB decoded PDF page stream.
- DOCX/XLSX OOXML preflight rejects invalid archives, duplicate members, absolute/traversal paths, and declared ZIP expansion limit violations before a format library reads the archive.
- Runtime dependency ranges are `python-docx>=1.2,<2.0`, `openpyxl>=3.1,<4.0`, `pypdf>=6.0,<7.0`, and `defusedxml>=0.7,<1.0`; exact resolved direct/transitive versions belong in `requirements-dev.lock`.
- Unit tests use deterministic synthetic byte fixtures, no network, no external process, no model, no OCR, and no real shipyard/customer data.

---

### Task 1: Dependency Closure and Common Parser Contract

**Files:**
- Create: `services/ingestion/parser.py`
- Modify: `services/ingestion/__init__.py`
- Modify: `pyproject.toml`
- Modify: `requirements-dev.lock`
- Create: `tests/unit/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Python standard library only for the contract.
- Produces: `DocumentFormat`, `ParsedBlockKind`, `ParserErrorCode`, `ParserError`, `Parser`, `ParsedBlock`, `ParsedDocument`, `TableCells`, `normalize_block_text`, `normalize_table_cell`, `render_table`, and `validate_source_bytes`.

- [ ] **Step 1: Add the public dependency ranges**

Add these runtime entries to `[project].dependencies` in `pyproject.toml`:

```toml
"defusedxml>=0.7,<1.0",
"openpyxl>=3.1,<4.0",
"pypdf>=6.0,<7.0",
"python-docx>=1.2,<2.0",
```

Install the approved ranges into the shared project virtual environment:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip install \
  "defusedxml>=0.7,<1.0" \
  "openpyxl>=3.1,<4.0" \
  "pypdf>=6.0,<7.0" \
  "python-docx>=1.2,<2.0"
```

Record the exact resolved versions of the four direct dependencies plus newly
required `et_xmlfile` and `lxml` in alphabetical order in
`requirements-dev.lock`. Do not alter unrelated locked versions. Confirm the
lock is a closed environment with:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
```

Expected: `No broken requirements found.`

- [ ] **Step 2: Write contract tests before the contract exists**

Start `tests/unit/ingestion/test_parsers.py` with imports and tests equivalent
to:

```python
from dataclasses import FrozenInstanceError

import pytest

from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    render_table,
)


def test_parser_contract_builds_one_immutable_common_document() -> None:
    table = (("Item", "Qty"), ("Pump", "2"))
    block = ParsedBlock(
        ordinal=0,
        kind=ParsedBlockKind.TABLE,
        text=render_table(table),
        structural_path=("Equipment",),
        table=table,
    )
    parsed = ParsedDocument(format=DocumentFormat.MARKDOWN, blocks=(block,))

    assert parsed.blocks == (block,)
    with pytest.raises(FrozenInstanceError):
        block.text = "changed"  # type: ignore[misc]


def test_parser_error_has_typed_code_and_fixed_message() -> None:
    error = ParserError(ParserErrorCode.OCR_REQUIRED)
    assert error.code is ParserErrorCode.OCR_REQUIRED
    assert str(error) == "PDF has no extractable text layer"
```

Add parameterized tests for every fixed error code/message and validation
tests for:

- non-integer/boolean/negative ordinals;
- non-contiguous ParsedDocument ordinals;
- blank text, path, and sheet values;
- invalid page values including `True` and zero;
- PAGE without page or with table;
- TABLE without cells, with page, with ragged/empty-only cells, or mismatched
  canonical text;
- non-TABLE with cells;
- sheet metadata on a non-XLSX document;
- empty ParsedDocument;
- CRLF/CR normalization without Unicode compatibility normalization; and
- exact tab/newline canonical table rendering with trailing empty rows/columns
  removed and interior empty cells retained.

- [ ] **Step 3: Run the contract test to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py -v
```

Expected: collection error because the parser contract names are absent from
`services.ingestion`.

- [ ] **Step 4: Implement the minimum immutable contract**

In `services/ingestion/parser.py`, define the exact enums, dataclasses, fixed
message mapping, Protocol, normalizers, render helper, and constants from the
spec. `ParserError` accepts only a code:

```python
class ParserError(RuntimeError):
    def __init__(self, code: ParserErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])
```

`validate_source_bytes(content)` must reject non-bytes as INVALID_DOCUMENT,
empty bytes as EMPTY_DOCUMENT, and bytes beyond `MAX_SOURCE_BYTES` as
RESOURCE_LIMIT. Dataclass validation raises `ValueError` with fixed
field-oriented messages; adapters translate public parsing failures into
`ParserError`.

`ParsedDocument.__post_init__` must also enforce the format/location rules and
the block-count/total-text limits. Export every public contract name from
`services/ingestion/__init__.py` without removing the Task 009 exports.

- [ ] **Step 5: Run contract GREEN and compatibility checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py \
  tests/unit/ingestion/test_document_store.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion tests/unit/ingestion/test_parsers.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion tests/unit/ingestion/test_parsers.py
```

Expected: all pass.

- [ ] **Step 6: Commit the dependency and contract slice**

```bash
git add pyproject.toml requirements-dev.lock services/ingestion \
  tests/unit/ingestion/test_parsers.py
git commit -m "feat: add common parser contracts"
```

---

### Task 2: Synthetic Fixture Builders and TXT/Markdown Adapters

**Files:**
- Create: `tests/fixtures/parser_documents.py`
- Create: `adapters/parsers/__init__.py`
- Create: `adapters/parsers/text.py`
- Create: `adapters/parsers/markdown.py`
- Modify: `tests/unit/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Task 1 parser records, normalizers, limits, and errors.
- Produces: `TxtParser` and `MarkdownParser`; fixture helpers `synthetic_txt_bytes()` and `synthetic_markdown_bytes()`.

- [ ] **Step 1: Add failing TXT and Markdown behavior tests**

Add synthetic builders returning bytes only:

```python
def synthetic_txt_bytes() -> bytes:
    return "\ufeff合成船厂规范\r\n\r\n泵组检查。\r\n第二行。".encode("utf-8")


def synthetic_markdown_bytes() -> bytes:
    return (
        "# 合成规范\n\n"
        "## 泵组\n\n"
        "检查轴封。\n\n"
        "| 项目 | 数量 |\n| --- | ---: |\n| 泵 | 2 |\n"
    ).encode()
```

Tests must assert:

```python
def test_txt_parser_returns_common_paragraph_blocks() -> None:
    parsed = TxtParser().parse(synthetic_txt_bytes())
    assert parsed.format is DocumentFormat.TXT
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.PARAGRAPH,
    ]
    assert parsed.blocks[1].text == "泵组检查。\n第二行。"


def test_markdown_parser_preserves_heading_path_and_whole_table() -> None:
    parsed = MarkdownParser().parse(synthetic_markdown_bytes())
    assert [block.ordinal for block in parsed.blocks] == list(
        range(len(parsed.blocks))
    )
    assert parsed.blocks[-1].kind is ParsedBlockKind.TABLE
    assert parsed.blocks[-1].structural_path == ("合成规范", "泵组")
    assert parsed.blocks[-1].table == (("项目", "数量"), ("泵", "2"))
```

Add explicit tests for UTF-8 BOM, Setext headings, shallower heading path
replacement, raw HTML/fenced code treated as literal text, ragged Markdown
table normalization, invalid UTF-8, NUL, all-blank input, exact source-size
boundary, and oversized block output. All failures assert both typed code and
fixed message.

- [ ] **Step 2: Run the two focused nodes to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py::test_txt_parser_returns_common_paragraph_blocks \
  tests/unit/ingestion/test_parsers.py::test_markdown_parser_preserves_heading_path_and_whole_table \
  -v
```

Expected: import error because `adapters.parsers` does not exist.

- [ ] **Step 3: Implement TXT and deterministic Markdown parsing**

`TxtParser.format` returns `DocumentFormat.TXT`; `MarkdownParser.format`
returns `DocumentFormat.MARKDOWN`. Both call `validate_source_bytes`, decode
`utf-8-sig`, reject NUL, and translate decode failures to
`UNSUPPORTED_ENCODING`.

TXT splits normalized text on one-or-more blank lines. Markdown uses a
single-pass line state machine:

- recognize ATX and Setext headings outside a paragraph/table;
- flush accumulated paragraph lines before a new structural block;
- maintain a six-level heading list, truncating deeper levels when a heading
  arrives;
- recognize a pipe-table header only when immediately followed by a valid
  delimiter row; and
- pad short rows to the header width and reject rows wider than
  `MAX_TABLE_COLUMNS`.

Do not parse HTML, fetch links, or execute fenced code. They remain paragraph
text. Build ParsedDocument last so cross-format limits validate the complete
output.

- [ ] **Step 4: Run adapter GREEN and static checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py -k "txt or markdown" -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  adapters/parsers/text.py adapters/parsers/markdown.py \
  tests/fixtures/parser_documents.py tests/unit/ingestion/test_parsers.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  adapters/parsers/text.py adapters/parsers/markdown.py \
  tests/fixtures/parser_documents.py tests/unit/ingestion/test_parsers.py
```

Expected: all pass.

- [ ] **Step 5: Commit the text adapters**

```bash
git add adapters/parsers tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
git commit -m "feat: parse text and markdown documents"
```

---

### Task 3: OOXML Preflight and DOCX Adapter

**Files:**
- Create: `adapters/parsers/_common.py`
- Create: `adapters/parsers/docx.py`
- Modify: `adapters/parsers/__init__.py`
- Modify: `tests/fixtures/parser_documents.py`
- Modify: `tests/unit/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Task 1 records/errors/limits and `python-docx`.
- Produces: `validate_ooxml_archive(content: bytes) -> None`, `DocxParser`, and `synthetic_docx_bytes()`.

- [ ] **Step 1: Write failing ordered DOCX test and archive-security tests**

Build the fixture in memory with `docx.Document`, Title, Heading 1, paragraph,
Heading 2, and a two-row table. Save to `BytesIO` and return bytes.

Add:

```python
def test_docx_parser_preserves_body_order_hierarchy_and_table() -> None:
    parsed = DocxParser().parse(synthetic_docx_bytes())
    assert parsed.format is DocumentFormat.DOCX
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.TITLE,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.TABLE,
    ]
    assert parsed.blocks[-1].structural_path == (
        "合成船级规则",
        "机械系统",
        "泵组",
    )
    assert parsed.blocks[-1].table == (("检查项", "结果"), ("轴封", "合格"))
```

Create small in-memory ZIP cases and assert exact errors for invalid ZIP,
duplicate names, `/absolute.xml`, `../escape.xml`, `..\\escape.xml`, too many
entries, declared uncompressed total beyond 100 MiB, and compression ratio
above 100. Also test malformed DOCX, blank DOCX, and a relationship whose
target is an HTTP URL; parsing must not make a network call.

- [ ] **Step 2: Run the primary DOCX node to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py::test_docx_parser_preserves_body_order_hierarchy_and_table \
  -v
```

Expected: import error because `DocxParser` is absent.

- [ ] **Step 3: Implement ZIP preflight and DOCX parsing**

`validate_ooxml_archive` uses `ZipFile(BytesIO(content))` and member metadata
only. Normalize member names by replacing backslashes with slashes before
checking `PurePosixPath`; reject duplicate normalized names and every listed
limit/path violation. Translate invalid ZIP to INVALID_DOCUMENT and expansion
limits to RESOURCE_LIMIT.

`DocxParser.parse` validates source bytes, runs preflight, calls
`docx.Document(BytesIO(content))`, and iterates `document.iter_inner_content()`.
Use public `Paragraph` and `Table` types to dispatch. Match Title and exact
`Heading [1-9]` styles; ordinary styles become PARAGRAPH. Convert each top-level
table into one rectangular table after accounting for repeated merged-cell
objects. Catch expected `ValueError`, `KeyError`, ZIP, XML, and package-open
errors and return INVALID_DOCUMENT without exception text.

- [ ] **Step 4: Run DOCX GREEN, full contract regression, and static checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py -k "docx or ooxml or contract" -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  adapters/parsers/_common.py adapters/parsers/docx.py \
  tests/fixtures/parser_documents.py tests/unit/ingestion/test_parsers.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  adapters/parsers/_common.py adapters/parsers/docx.py \
  tests/fixtures/parser_documents.py tests/unit/ingestion/test_parsers.py
```

Expected: all pass.

- [ ] **Step 5: Commit the DOCX slice**

```bash
git add adapters/parsers tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
git commit -m "feat: parse structured docx documents"
```

---

### Task 4: XLSX Adapter

**Files:**
- Create: `adapters/parsers/xlsx.py`
- Modify: `adapters/parsers/__init__.py`
- Modify: `tests/fixtures/parser_documents.py`
- Modify: `tests/unit/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Task 1 table contract, Task 3 OOXML preflight, and `openpyxl`.
- Produces: `XlsxParser` and `synthetic_xlsx_bytes()`.

- [ ] **Step 1: Write failing XLSX structure and safety tests**

The synthetic workbook must contain:

- sheet `泵组` with headers, a formula cell `=1+1`, a date, a boolean, and an
  interior blank cell; and
- sheet `材料` with one small table.

Add:

```python
def test_xlsx_parser_returns_one_whole_table_per_nonempty_sheet() -> None:
    parsed = XlsxParser().parse(synthetic_xlsx_bytes())
    assert parsed.format is DocumentFormat.XLSX
    assert [block.sheet for block in parsed.blocks] == ["泵组", "材料"]
    assert all(block.kind is ParsedBlockKind.TABLE for block in parsed.blocks)
    assert parsed.blocks[0].structural_path == ("泵组",)
    assert "=1+1" in parsed.blocks[0].text
    assert "TRUE" in parsed.blocks[0].text
```

Add tests for blank sheets being skipped, an all-blank workbook, formulas
remaining literal, ISO date/time/datetime values, deterministic numeric text,
interior empty-cell preservation, trailing empty-row/column trimming, workbook
close on success and failure, archive preflight reuse, row/column/cell limits,
malformed XLSX, and exact parser type/error messages. Patch
`openpyxl.load_workbook` in one focused test to assert these exact keyword
arguments: `read_only=True`, `data_only=False`, `keep_links=False`, and
`keep_vba=False`.

- [ ] **Step 2: Run the primary XLSX node to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py::test_xlsx_parser_returns_one_whole_table_per_nonempty_sheet \
  -v
```

Expected: import error because `XlsxParser` is absent.

- [ ] **Step 3: Implement read-only non-executing workbook parsing**

Validate bytes and OOXML archive first. Load from `BytesIO` with the four exact
safe flags and close in `finally`. Iterate worksheets in workbook order and
rows with `values_only=True`; count rows, maximum columns, and cells during
iteration rather than trusting worksheet dimension metadata.

Convert values exactly as specified: None to empty, booleans to uppercase,
date/time/datetime to `isoformat()`, strings/formulas unchanged before cell
normalization, and numeric values through `str(value)`. Emit one TABLE per
non-empty sheet; an empty workbook raises EMPTY_DOCUMENT. Translate expected
OOXML/openpyxl errors to INVALID_DOCUMENT with no raw exception.

- [ ] **Step 4: Run XLSX GREEN and static checks**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py -k "xlsx or ooxml" -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  adapters/parsers/xlsx.py tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  adapters/parsers/xlsx.py tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
```

Expected: all pass. If `openpyxl` lacks inline typing, add the narrowest
`# type: ignore[import-untyped]` to its import only; do not disable mypy for the
module or parser package.

- [ ] **Step 5: Commit the XLSX slice**

```bash
git add adapters/parsers tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
git commit -m "feat: parse xlsx worksheets safely"
```

---

### Task 5: Text-Layer PDF Adapter

**Files:**
- Create: `adapters/parsers/pdf.py`
- Modify: `adapters/parsers/__init__.py`
- Modify: `tests/fixtures/parser_documents.py`
- Modify: `tests/unit/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Task 1 page contract/limits/errors and `pypdf`.
- Produces: `PdfParser`, `synthetic_pdf_bytes()`, `blank_pdf_bytes()`, and `encrypted_pdf_bytes()`.

- [ ] **Step 1: Write failing PDF page and OCR-boundary tests**

The fixture helper must create a minimal deterministic two-page PDF containing
text streams `Synthetic page one` and `Synthetic page two` without adding a
report-generation dependency. Use a small byte builder that calculates object
offsets and xref entries; validate it through the production parser rather
than duplicating extraction logic.

Add:

```python
def test_pdf_parser_preserves_one_based_page_locations() -> None:
    parsed = PdfParser().parse(synthetic_pdf_bytes())
    assert parsed.format is DocumentFormat.PDF
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.PAGE,
        ParsedBlockKind.PAGE,
    ]
    assert [block.page for block in parsed.blocks] == [1, 2]
    assert "Synthetic page one" in parsed.blocks[0].text


def test_pdf_without_text_layer_requires_ocr_but_never_invokes_it() -> None:
    with pytest.raises(ParserError) as captured:
        PdfParser().parse(blank_pdf_bytes())
    assert captured.value.code is ParserErrorCode.OCR_REQUIRED
    assert str(captured.value) == "PDF has no extractable text layer"
```

Add tests for a blank middle page preserving page gaps, encrypted PDF,
malformed PDF, empty bytes, page-count limit, page-stream limit, NUL extracted
text, output-char limit, and exact safe errors. Add an AST/import assertion
that `adapters/parsers/pdf.py` imports no OCR, image-rendering, model, network,
retrieval, or persistence package.

Build `blank_pdf_bytes()` with `PdfWriter.add_blank_page()`. Build
`encrypted_pdf_bytes()` with a fresh `PdfWriter`, one blank page, and
`writer.encrypt("synthetic-test-password")`; the password is a fixed synthetic
test value and the production parser must not attempt it.

- [ ] **Step 2: Run the primary PDF/OCR nodes to verify RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py::test_pdf_parser_preserves_one_based_page_locations \
  tests/unit/ingestion/test_parsers.py::test_pdf_without_text_layer_requires_ocr_but_never_invokes_it \
  -v
```

Expected: import error because `PdfParser` is absent.

- [ ] **Step 3: Implement bounded text-layer PDF extraction**

Validate bytes, construct `PdfReader(BytesIO(content), strict=True)`, reject
`reader.is_encrypted` without trying a password, then enforce page count.
For each page, obtain its content stream; if present, decode once, enforce the
10 MiB limit, then call `extract_text()`. Normalize non-blank text and emit a
PAGE block with the original one-based page number. Skip blank pages but not
their numbering. If no block remains, raise OCR_REQUIRED.

Catch expected pypdf read/decryption/stream errors and translate them to the
appropriate fixed ParserError. Do not catch ParserError raised by limits and
do not import or invoke OCR.

- [ ] **Step 4: Run PDF GREEN and the complete parser unit module**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  adapters/parsers/pdf.py tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  adapters/parsers/pdf.py tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
```

Expected: all pass.

- [ ] **Step 5: Commit the PDF slice**

```bash
git add adapters/parsers tests/fixtures/parser_documents.py \
  tests/unit/ingestion/test_parsers.py
git commit -m "feat: parse text-layer pdf documents"
```

---

### Task 6: Public Documentation, Architecture Guard, and Complete Gate

**Files:**
- Modify: `docs/03-knowledge-system.md`
- Modify: `tests/unit/ingestion/test_parsers.py`
- Modify only if a verified Task 010 defect appears: Task 010 implementation files listed above.

**Interfaces:**
- Consumes: the complete parser contract and five adapters.
- Produces: documented behavior, architecture/scope regression coverage, and final Definition-of-Done evidence.

- [ ] **Step 1: Add an architecture and common-surface regression test**

Use `ast` to inspect `adapters/parsers/*.py`. Assert every non-relative import
root belongs to this allow-list:

```python
{
    "collections",
    "datetime",
    "docx",
    "enum",
    "io",
    "lxml",
    "openpyxl",
    "pathlib",
    "pypdf",
    "re",
    "services",
    "typing",
    "zipfile",
}
```

Adjust the list only for an actually used Python standard-library module.
Explicitly assert none of these roots appear: `requests`, `httpx`, `urllib`,
`socket`, `pytesseract`, `ocrmypdf`, `fitz`, `pdf2image`, `sqlalchemy`,
`adapters.ocr`, `services.retrieval`, or model SDKs.

Instantiate all five adapters as `tuple[Parser, ...]`, parse their matching
synthetic bytes, and assert each result is a ParsedDocument with its declared
format and non-empty blocks.

- [ ] **Step 2: Update public knowledge-system documentation**

Extend `docs/03-knowledge-system.md` ingestion section with:

- common immutable ordered parser blocks;
- byte-input and replaceable adapter boundary;
- supported TXT/Markdown/DOCX/XLSX/text-PDF behavior;
- page/sheet/heading/table preservation;
- fixed typed errors and resource limits;
- XLSX formulas remain literal and external links/macros are not executed;
- textless PDF returns OCR_REQUIRED and OCR is disabled in Task 010; and
- parsed content remains untrusted data and Task 011 owns chunking.

- [ ] **Step 3: Run focused acceptance and dependency gates**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py \
  tests/unit/ingestion/test_document_store.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
```

Expected: every parser format is covered, zero skips, and dependency closure is
clean.

- [ ] **Step 4: Run the complete quality gate**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
git diff --check 4a002c0...HEAD
git diff --name-only 4a002c0...HEAD
```

Expected: dependency check, all tests, Ruff, and mypy pass. Changed files are
restricted to the approved spec/plan and Task 010 paths. No migration appears.

- [ ] **Step 5: Verify acceptance criteria explicitly**

Record evidence for:

1. all five adapters return the same immutable ParsedDocument representation;
2. every public failure has a ParserErrorCode and fixed safe message;
3. PDF no-text behavior returns OCR_REQUIRED with no OCR import or invocation;
4. deterministic synthetic byte fixtures cover TXT, Markdown, DOCX, XLSX, and
   text-layer PDF;
5. heading paths, whole tables, sheet names, literal formulas, and PDF pages
   survive parsing; and
6. no path input, external process, network, model, persistence, chunking,
   Task 011, or real customer data was added.

- [ ] **Step 6: Commit documentation and final guards**

```bash
git add docs/03-knowledge-system.md tests/unit/ingestion/test_parsers.py
git commit -m "docs: document safe parser adapters"
```

- [ ] **Step 7: Request final review and stop before Task 011**

Request a spec/code/security review across `4a002c0...HEAD` against AGENTS.md,
Task 010, and the approved design. Resolve every verified P0/P1/P2 finding with
focused TDD, rerun the full gate after material fixes, and report P3 items as
known limitations. Do not merge, push, or start Task 011 without user choice.
