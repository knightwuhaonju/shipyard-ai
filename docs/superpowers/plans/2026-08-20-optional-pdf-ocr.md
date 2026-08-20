# Optional PDF OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicitly enabled, bytes-only OCR fallback parser for scanned PDFs while keeping the OCR engine replaceable and absent from service/domain interfaces.

**Architecture:** `services.ingestion.ocr` owns immutable OCR page results, the `OcrPort`, and an `OcrFallbackParser` that wraps the existing text-layer `Parser`. The wrapper calls OCR only for `OCR_REQUIRED`; `adapters.ocr.fake` provides the sole deterministic adapter in Task 012, and all OCR output is normalized into existing PDF `PAGE` blocks under existing parser budgets.

**Tech Stack:** Python 3.12, dataclasses, typing `Protocol`, existing ingestion parser contracts, pypdf-backed `PdfParser`, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-20-optional-pdf-ocr-design.md`

## Global Constraints

- OCR is disabled by default and enabled only through explicit `ocr=` dependency injection.
- `services.ingestion.ocr` may depend on service/parser contracts but must never import adapters, OCR/model SDKs, pypdf, network, filesystem, subprocess, persistence, retrieval, or authorization packages.
- `OcrPort` accepts only original PDF bytes and returns only immutable page text plus original one-based page numbers.
- Only `ParserErrorCode.OCR_REQUIRED` may trigger OCR. Every other primary parser result or error bypasses OCR unchanged.
- OCR pages remain untrusted document content and must obey `MAX_PDF_PAGES`, `MAX_BLOCKS`, `MAX_BLOCK_CHARS`, and `MAX_TOTAL_TEXT_CHARS`.
- Unit tests use deterministic synthetic bytes and `FakeOcrAdapter`; no external OCR, model, network, file, or subprocess call is permitted.
- No dependency, migration, domain, parser-adapter, retrieval, authorization, or Task 013 file may change.
- Every behavior change follows RED → minimal GREEN → relevant suite → Ruff → mypy.

---

### Task 1: Define the immutable OCR service contract

**Files:**
- Create: `services/ingestion/ocr.py`
- Modify: `services/ingestion/__init__.py`
- Create: `tests/unit/ingestion/test_ocr_flow.py`

**Interfaces:**
- Consumes: existing `DocumentFormat`, `ParsedDocument`, and `Parser` contracts from `services.ingestion.parser`.
- Produces: `OcrPage(page: int, text: str)` and `OcrPort.recognize_pdf(content: bytes) -> tuple[OcrPage, ...]` for Task 2.

- [ ] **Step 1: Write the contract import RED test**

Create `tests/unit/ingestion/test_ocr_flow.py` with the future public imports and one immutable record test:

```python
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from services.ingestion import OcrPage, OcrPort


def test_ocr_page_is_an_exact_immutable_port_record() -> None:
    page = OcrPage(page=3, text="  synthetic OCR text  ")

    assert type(page) is OcrPage
    assert page.page == 3
    assert page.text == "  synthetic OCR text  "
    with pytest.raises(FrozenInstanceError):
        page.page = 4  # type: ignore[misc]


def _accept_port(port: OcrPort) -> OcrPort:
    return port
```

The helper is used in Task 2 with `FakeOcrAdapter`; it ensures static protocol compatibility without runtime engine coupling.

- [ ] **Step 2: Run the node and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py::test_ocr_page_is_an_exact_immutable_port_record -v
```

Expected: collection fails because `OcrPage` and `OcrPort` are not exported and `services.ingestion.ocr` does not exist.

- [ ] **Step 3: Implement the minimum contract**

Create `services/ingestion/ocr.py`:

```python
"""Optional, engine-independent PDF OCR service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrPage:
    page: int
    text: str

    def __post_init__(self) -> None:
        if type(self.page) is not int or self.page <= 0:
            raise ValueError("page must be a positive integer")
        if type(self.text) is not str or "\x00" in self.text:
            raise ValueError("text must be a string without NUL")


class OcrPort(Protocol):
    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]: ...
```

Import both names in `services/ingestion/__init__.py` and add them to the existing `__all__` without removing or reordering unrelated public contracts.

- [ ] **Step 4: Run the contract node and confirm GREEN**

Run the Step 2 command again. Expected: `1 passed`.

- [ ] **Step 5: Add exact constructor validation tests**

Add literal parameterized cases:

```python
@pytest.mark.parametrize("page", [0, -1, True, 1.0, "1"])
def test_ocr_page_rejects_invalid_page(page: object) -> None:
    with pytest.raises(ValueError, match="^page must be a positive integer$"):
        OcrPage(page=cast(int, page), text="synthetic")


@pytest.mark.parametrize("text", [None, b"text", "bad\x00text"])
def test_ocr_page_rejects_invalid_text(text: object) -> None:
    with pytest.raises(ValueError, match="^text must be a string without NUL$"):
        OcrPage(page=1, text=cast(str, text))
```

Also assert that blank text is accepted because the orchestrator, not the port record, decides whether a processed page produces a block.

- [ ] **Step 6: Verify Task 1 scope**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion/ocr.py services/ingestion/__init__.py \
  tests/unit/ingestion/test_ocr_flow.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion/ocr.py services/ingestion/__init__.py \
  tests/unit/ingestion/test_ocr_flow.py
```

Expected: all pass with no warnings.

- [ ] **Step 7: Commit the contract slice**

```bash
git add services/ingestion/ocr.py services/ingestion/__init__.py \
  tests/unit/ingestion/test_ocr_flow.py
git commit -m "feat: define PDF OCR port"
```

---

### Task 2: Add explicit OCR fallback orchestration and deterministic fake

**Files:**
- Modify: `services/ingestion/ocr.py`
- Modify: `services/ingestion/__init__.py`
- Create: `adapters/ocr/__init__.py`
- Create: `adapters/ocr/fake.py`
- Modify: `tests/unit/ingestion/test_ocr_flow.py`

**Interfaces:**
- Consumes: Task 1 `OcrPage` and `OcrPort`, existing `Parser`, `PdfParser`, and `ParsedDocument` contracts.
- Produces: `OcrFallbackParser(primary: Parser, *, ocr: OcrPort | None = None)` and `FakeOcrAdapter(pages: tuple[OcrPage, ...])`.

- [ ] **Step 1: Add the existing disabled-behavior guard**

Use the real parser and synthetic fixture before adding fallback code:

```python
from adapters.parsers import PdfParser
from services.ingestion import ParserError, ParserErrorCode
from tests.fixtures.parser_documents import blank_pdf_bytes


def test_textless_pdf_requires_ocr_before_task_012_fallback_exists() -> None:
    with pytest.raises(ParserError) as captured:
        PdfParser().parse(blank_pdf_bytes())

    assert captured.value.code is ParserErrorCode.OCR_REQUIRED
    assert str(captured.value) == "PDF has no extractable text layer"
```

Run the node. Expected: it passes and protects Task 010 behavior before the new wrapper is introduced.

- [ ] **Step 2: Write the primary injected OCR RED test**

Add imports for `FakeOcrAdapter` and `OcrFallbackParser`, then add:

```python
def test_injected_fake_ocr_preserves_original_page_numbers() -> None:
    content = blank_pdf_bytes()
    fake = FakeOcrAdapter(
        (
            OcrPage(page=1, text="  Synthetic OCR page one  "),
            OcrPage(page=3, text="Synthetic OCR page three"),
        )
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(content)

    assert parsed.format is DocumentFormat.PDF
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.PAGE,
        ParsedBlockKind.PAGE,
    ]
    assert [block.ordinal for block in parsed.blocks] == [0, 1]
    assert [block.page for block in parsed.blocks] == [1, 3]
    assert [block.text for block in parsed.blocks] == [
        "Synthetic OCR page one",
        "Synthetic OCR page three",
    ]
    assert fake.received_contents == (content,)
    assert _accept_port(fake) is fake
```

- [ ] **Step 3: Run the primary node and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py::test_injected_fake_ocr_preserves_original_page_numbers -v
```

Expected: collection fails because `OcrFallbackParser` and `adapters.ocr` are absent.

- [ ] **Step 4: Implement the deterministic fake**

Create `adapters/ocr/fake.py`:

```python
"""Deterministic OCR adapter for tests and local contract checks."""

from services.ingestion.ocr import OcrPage


class FakeOcrAdapter:
    def __init__(self, pages: tuple[OcrPage, ...]) -> None:
        if type(pages) is not tuple or any(type(page) is not OcrPage for page in pages):
            raise ValueError("pages must be a tuple of OcrPage")
        self._pages = pages
        self._received_contents: list[bytes] = []

    @property
    def received_contents(self) -> tuple[bytes, ...]:
        return tuple(self._received_contents)

    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]:
        self._received_contents.append(content)
        return self._pages
```

Create `adapters/ocr/__init__.py` with `FakeOcrAdapter` as its only public export.

- [ ] **Step 5: Implement the minimum valid fallback flow**

Extend `services/ingestion/ocr.py` with imports from `services.ingestion.parser` and:

```python
class OcrFallbackParser:
    def __init__(self, primary: Parser, *, ocr: OcrPort | None = None) -> None:
        if primary.format is not DocumentFormat.PDF:
            raise ValueError("primary parser must use PDF format")
        self._primary = primary
        self._ocr = ocr

    @property
    def format(self) -> DocumentFormat:
        return DocumentFormat.PDF

    def parse(self, content: bytes) -> ParsedDocument:
        validate_source_bytes(content)
        try:
            return self._primary.parse(content)
        except ParserError as error:
            if error.code is not ParserErrorCode.OCR_REQUIRED or self._ocr is None:
                raise

        pages = self._ocr.recognize_pdf(content)
        return _ocr_document(pages)
```

For the first GREEN, `_ocr_document()` may assume the valid Task 2 tuple while still using `normalize_block_text()`, omitting blank normalized pages, constructing contiguous `PAGE` blocks, and returning `ParsedDocument(format=PDF, ...)`. Task 3 adds hostile-boundary validation before completion; do not add untested Task 3 branches early.

Export `OcrFallbackParser` from `services.ingestion`.

- [ ] **Step 6: Run the primary node and confirm GREEN**

Run the Step 3 command again. Expected: `1 passed`.

- [ ] **Step 7: Add disabled, text-layer bypass, and error-routing tests**

Add these behaviors with real synthetic PDF bytes:

```python
def test_ocr_is_disabled_by_default() -> None:
    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser()).parse(blank_pdf_bytes())
    assert captured.value.code is ParserErrorCode.OCR_REQUIRED


def test_text_layer_pdf_bypasses_injected_ocr() -> None:
    fake = FakeOcrAdapter((OcrPage(page=1, text="must not run"),))
    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(synthetic_pdf_bytes())
    assert [block.page for block in parsed.blocks] == [1, 2]
    assert fake.received_contents == ()
```

Parameterize empty, encrypted, malformed, and resource-limit primary failures and assert the exact safe `ParserError` code plus `fake.received_contents == ()`. Add a constructor test rejecting a non-PDF primary parser with the fixed message.

- [ ] **Step 8: Add page-gap and fake contract tests**

Return pages 1 blank and 3 non-blank; assert the only block has ordinal `0` and page `3`. Assert `FakeOcrAdapter` rejects non-tuples and wrong item types with `pages must be a tuple of OcrPage`, returns configured pages unchanged, and exposes call history as an immutable tuple.

- [ ] **Step 9: Verify Task 2 scope**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_parsers.py tests/unit/ingestion/test_ocr_flow.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check \
  services/ingestion/ocr.py services/ingestion/__init__.py \
  adapters/ocr tests/unit/ingestion/test_ocr_flow.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy \
  services/ingestion/ocr.py services/ingestion/__init__.py \
  adapters/ocr tests/unit/ingestion/test_ocr_flow.py
```

Expected: all pass.

- [ ] **Step 10: Commit the orchestration slice**

```bash
git add services/ingestion/ocr.py services/ingestion/__init__.py \
  adapters/ocr tests/unit/ingestion/test_ocr_flow.py
git commit -m "feat: add optional PDF OCR fallback"
```

---

### Task 3: Harden OCR output, document the contract, and run the complete gate

**Files:**
- Modify: `services/ingestion/ocr.py`
- Modify: `tests/unit/ingestion/test_ocr_flow.py`
- Modify: `docs/03-knowledge-system.md`

**Interfaces:**
- Consumes: Task 2 `OcrFallbackParser`, `OcrPage`, `OcrPort`, and `FakeOcrAdapter`.
- Produces: a safe public OCR boundary that maps hostile adapter results into existing parser errors and is documented for later ingestion callers.

- [ ] **Step 1: Write RED tests for invalid OCR result shapes**

Define a test-only bad port whose annotated method uses `cast` to return hostile objects through the real public wrapper. Add parameterized cases for a list instead of a tuple and an object instead of `OcrPage`; expect:

```python
with pytest.raises(ParserError) as captured:
    OcrFallbackParser(PdfParser(), ocr=bad_port).parse(blank_pdf_bytes())
assert captured.value.code is ParserErrorCode.INVALID_DOCUMENT
assert str(captured.value) == "document cannot be parsed"
```

Run these nodes before hardening. Expected: raw `AttributeError`, `TypeError`, or contract `ValueError`, proving the boundary is not yet safe.

- [ ] **Step 2: Write RED tests for page ordering and limits**

Use valid `OcrPage` records to cover duplicate pages `(1, 1)`, descending pages `(2, 1)`, and `page=MAX_PDF_PAGES + 1`. Expect `INVALID_DOCUMENT` for ordering and `RESOURCE_LIMIT` for the page limit.

Monkeypatch only existing numeric parser constants to small values and add exact-boundary/one-over tests for per-page and total text. The exact boundary must succeed; one over must return `RESOURCE_LIMIT`. An empty tuple and an all-blank tuple must return `EMPTY_DOCUMENT`.

Run the new nodes. Expected: at least one failure per missing validation branch, with no failure caused by a malformed test fixture.

- [ ] **Step 3: Implement one safe OCR result builder**

Replace the valid-only Task 2 helper with a single boundary function shaped as:

```python
def _ocr_document(result: object) -> ParsedDocument:
    if type(result) is not tuple:
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
    pages = cast(tuple[object, ...], result)
    blocks: list[ParsedBlock] = []
    previous_page = 0
    total_chars = 0

    for item in pages:
        if type(item) is not OcrPage:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        if item.page <= previous_page:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        if item.page > parser_contract.MAX_PDF_PAGES:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        previous_page = item.page
        try:
            text = normalize_block_text(item.text)
        except ValueError:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None
        if not text:
            continue
        if (
            len(blocks) >= parser_contract.MAX_BLOCKS
            or len(text) > parser_contract.MAX_BLOCK_CHARS
            or total_chars + len(text) > parser_contract.MAX_TOTAL_TEXT_CHARS
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        blocks.append(
            ParsedBlock(
                ordinal=len(blocks),
                kind=ParsedBlockKind.PAGE,
                text=text,
                page=item.page,
            )
        )
        total_chars += len(text)

    if not blocks:
        raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
    return ParsedDocument(format=DocumentFormat.PDF, blocks=tuple(blocks))
```

Import `services.ingestion.parser as parser_contract` for monkeypatchable shared limits. Do not catch exceptions around the OCR adapter call itself; expected adapters must already use `ParserError`, while unexpected programming errors remain visible.

- [ ] **Step 4: Run hostile-boundary tests and confirm GREEN**

Run all Step 1–2 nodes together. Expected: all pass with fixed safe messages and no cause chaining.

- [ ] **Step 5: Add AST architecture and public-surface guards**

Parse `services/ingestion/ocr.py` and `adapters/ocr/fake.py` with `ast`. Resolve relative imports and imported alias targets. Assert:

- the service imports only `__future__`, `dataclasses`, `typing`, and exact `services.ingestion.parser` targets;
- the fake imports only the Task 012 service contract;
- neither file imports or names `pypdf`, `fitz`, `pdf2image`, `pytesseract`, `ocrmypdf`, model SDKs, network clients, `socket`, `pathlib`, `os`, `subprocess`, SQLAlchemy, retrieval, authorization, or persistence modules; and
- `services.ingestion.__all__` retains all existing names and includes exactly the three Task 012 service names.

Add malicious source snippets proving relative and parent-module alias imports cannot bypass the test helper, following the hardened Task 011 AST-test pattern.

- [ ] **Step 6: Document the implemented Task 012 boundary**

Update `docs/03-knowledge-system.md` section `## 2. Ingestion` to state:

- text-layer PDF parsing remains primary;
- `OcrFallbackParser` is disabled unless `OcrPort` is explicitly injected;
- only `OCR_REQUIRED` invokes OCR;
- results become normalized PDF `PAGE` blocks with original page numbers and contiguous ordinals;
- the Task adds no real OCR engine and the fake is deterministic;
- OCR text is derived, untrusted content and original PDF/version remains authoritative; and
- OCR orchestration does not persist, chunk, retrieve, authorize, use paths, or make external calls.

Replace the now-stale sentence that says Task 012 is future work. Do not document a production OCR engine as implemented.

- [ ] **Step 7: Run focused acceptance and relevant suites**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/unit/ingestion/test_ocr_flow.py \
  tests/unit/ingestion/test_parsers.py \
  tests/unit/ingestion/test_chunker.py \
  tests/unit/domain/test_documents.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest \
  tests/integration/test_document_versions.py -v
```

Expected: zero failures or skips attributable to Task 012; OCR-produced documents remain compatible with the existing chunk/document-version contracts without a migration.

- [ ] **Step 8: Run the complete project gate and scope audit**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test \
  make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pip check
git diff --check 0c1fecf...HEAD
git diff --name-only 0c1fecf...HEAD
```

Expected:

- all tests pass;
- Ruff prints `All checks passed!`;
- mypy reports no issues;
- pip reports `No broken requirements found.`;
- only the approved Task 012 design, plan, service contract/export, fake
  adapter, OCR unit test, and knowledge-system document appear; and
- no dependency, migration, domain, parser adapter, retrieval, authorization,
  model, real OCR engine, or Task 013 file appears.

- [ ] **Step 9: Record acceptance evidence**

The final report must map exact test nodes to all acceptance criteria:

1. disabled scanned PDF returns the existing safe `OCR_REQUIRED`;
2. enabled fake OCR preserves original page numbers and gaps;
3. architecture guards prove no OCR engine leaks into service/domain
   interfaces; and
4. every OCR success test uses `FakeOcrAdapter` with synthetic bytes.

Also report public error behavior, resource limits, source-of-truth treatment,
no real data/secrets, and no Task 013 work.

- [ ] **Step 10: Commit the hardening/documentation slice**

```bash
git add services/ingestion/ocr.py tests/unit/ingestion/test_ocr_flow.py \
  docs/03-knowledge-system.md
git commit -m "test: harden optional OCR boundary"
```

- [ ] **Step 11: Request final independent review and stop before Task 013**

Request a read-only spec/code/security review across `0c1fecf...HEAD` against
`AGENTS.md`, `tasks/012-ocr-adapter.md`, this specification, and this plan.
Resolve every verified P0/P1/P2 finding with focused TDD, rerun the complete
gate after material fixes, and report P3 findings as known limitations. Do not
merge, push, or begin Task 013 without explicit user choice.
