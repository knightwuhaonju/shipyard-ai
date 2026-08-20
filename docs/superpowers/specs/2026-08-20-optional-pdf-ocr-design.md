# Optional PDF OCR Design

**Date:** 2026-08-20
**Status:** Approved for implementation planning
**Task:** 012 — Optional scanned-PDF OCR adapter

## 1. Purpose

Task 012 adds an optional OCR fallback boundary for scanned PDFs without
coupling ingestion services to an OCR engine. The existing `PdfParser` remains
the authority for validating PDF bytes, extracting an existing text layer,
and detecting the `OCR_REQUIRED` condition. A new service-level parser wrapper
may invoke an explicitly injected OCR port only after that condition.

OCR is disabled by default. No real OCR library, model, external process, or
network service is added by this Task. Unit tests use a deterministic fake
adapter.

## 2. Non-goals

Task 012 does not:

- change `PdfParser` into an OCR-capable adapter;
- choose or install a production OCR engine;
- render PDF pages inside the service layer;
- accept filesystem paths, storage handles, credentials, authorization
  contexts, or model configuration at the OCR boundary;
- persist, chunk, index, retrieve, or authorize OCR output;
- change `ParsedDocument`, `ParsedBlock`, or `DocumentChunk` domain contracts;
  or
- begin Task 013 or any later Task.

## 3. Architecture and dependency direction

The service package owns the replaceable port and orchestration:

```text
caller
  -> OcrFallbackParser(primary=PdfParser(), ocr=None)
       -> primary.parse(pdf_bytes)
            -> ParsedDocument                 # text layer exists
            -> ParserError(OCR_REQUIRED)       # scanned/textless
                 -> re-raise when ocr is None
                 -> OcrPort.recognize_pdf(bytes) when explicitly injected
                      -> tuple[OcrPage, ...]
                 -> validated PDF ParsedDocument with PAGE blocks
```

The allowed dependency direction is:

```text
caller -> services.ingestion.ocr -> services.ingestion.parser
adapter -> services.ingestion.ocr
```

`services.ingestion.ocr` must not import `adapters`, `pypdf`, an OCR SDK,
filesystem APIs, network clients, model SDKs, persistence, retrieval, or
authorization packages. A future production OCR implementation may live under
`adapters/ocr/`, but it must implement the same bytes-only port and translate
engine failures into the existing safe parser error contract.

## 4. Public contracts

The new service module exposes these contracts:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OcrPage:
    page: int
    text: str


class OcrPort(Protocol):
    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]: ...


class OcrFallbackParser:
    def __init__(self, primary: Parser, *, ocr: OcrPort | None = None) -> None: ...

    @property
    def format(self) -> DocumentFormat: ...

    def parse(self, content: bytes) -> ParsedDocument: ...
```

`OcrPage.page` is an original one-based PDF page number. Page numbers may have
gaps because blank pages may remain blank after OCR. `OcrPage.text` may be
blank so an adapter can report a processed page with no recognized text; the
orchestrator normalizes and omits such a block while preserving later page
numbers.

`OcrFallbackParser` implements the existing `Parser` protocol and always has
`DocumentFormat.PDF`. Its primary parser must also advertise PDF format.
Callers opt in by supplying `ocr=` explicitly. Constructing it without that
argument is the disabled default.

The ingestion package publicly exports `OcrPage`, `OcrPort`, and
`OcrFallbackParser`. The fake adapter is exported only from `adapters.ocr`.

## 5. Orchestration behavior

`OcrFallbackParser.parse()` follows this exact sequence:

1. Validate that `content` is non-empty exact bytes with the existing source
   byte validator. Invalid input never reaches either parser or OCR port.
2. Call the primary PDF parser once.
3. Return its `ParsedDocument` unchanged when a text layer is available.
4. Propagate every primary failure except `ParserErrorCode.OCR_REQUIRED`
   unchanged. Encrypted, malformed, unsupported, empty, and resource-limited
   input never triggers OCR.
5. When the primary returns `OCR_REQUIRED` and `ocr is None`, re-raise the same
   safe error. This is the default behavior.
6. When the primary returns `OCR_REQUIRED` and an OCR port is present, call
   `recognize_pdf()` exactly once with the same immutable source bytes.
7. Validate and normalize the returned pages, omit pages whose normalized text
   is blank, assign contiguous block ordinals, and return a PDF
   `ParsedDocument` containing `PAGE` blocks with the original page numbers.

The OCR port returns text and provenance only. It does not return parser
blocks, domain chunks, engine objects, confidence tensors, image handles, or
vendor-specific values.

## 6. OCR result validation and limits

The service treats adapter output as untrusted boundary data.

- The result must be an exact tuple of exact `OcrPage` values.
- Page values must be exact positive integers, strictly increasing, unique,
  and no greater than the existing `MAX_PDF_PAGES` limit.
- Text values must be exact strings without NUL.
- Text uses the existing `normalize_block_text()` behavior.
- Blank normalized pages do not produce blocks; later original page numbers
  remain unchanged.
- Each retained page must not exceed `MAX_BLOCK_CHARS`.
- Retained page count must not exceed `MAX_BLOCKS`.
- Total retained text must not exceed `MAX_TOTAL_TEXT_CHARS`.

Invalid shapes, values, duplicate/out-of-order pages, or NUL text become the
existing safe `ParserErrorCode.INVALID_DOCUMENT`. Page, block, per-page, and
total-text limit failures become `ParserErrorCode.RESOURCE_LIMIT`. A successful
OCR call with no retained text becomes `ParserErrorCode.EMPTY_DOCUMENT`.

No new public error class or error message is introduced. An OCR adapter must
raise `ParserError` for expected safe adapter failures. Unexpected programming
errors are not broadly swallowed by the service wrapper.

## 7. Deterministic fake adapter

`adapters/ocr/fake.py` provides `FakeOcrAdapter`. Its constructor accepts one
exact tuple of configured `OcrPage` results. `recognize_pdf()` returns those
results deterministically and records the exact bytes received in an immutable
inspection property so tests can prove whether fallback was invoked.

The fake performs no PDF parsing, rendering, OCR, file access, network access,
subprocess execution, or model call. It exists only to exercise the port and
service orchestration deterministically.

## 8. Security and source-of-truth behavior

- Original PDF bytes remain the source document; OCR text is a derived parsing
  artifact and never replaces document/version provenance.
- OCR text is untrusted document content. It can provide later retrieval facts
  but never execution instructions.
- No credentials or user identity cross the OCR port.
- No engine dependency leaks into domain or service interfaces.
- OCR is never silently enabled by environment variables, imports, or global
  registries.
- Unit tests make no external call and use only synthetic PDF bytes and the
  deterministic fake.

## 9. Test design

Before implementation, a guard test verifies that the existing `PdfParser`
still returns `OCR_REQUIRED` for a synthetic textless PDF. The primary RED test
then imports the absent OCR contracts, injects `FakeOcrAdapter`, returns pages
1 and 3, and expects PDF `PAGE` blocks with page values `[1, 3]` and contiguous
ordinals `[0, 1]`. It fails because the Task 012 service and fake do not yet
exist; the same node becomes the primary GREEN after the minimum implementation.

Additional tests cover:

- a normal text-layer PDF bypasses the injected fake completely;
- non-`OCR_REQUIRED` primary errors never call OCR;
- exact source bytes reach the fake once;
- blank OCR pages preserve later page gaps;
- empty OCR output maps to `EMPTY_DOCUMENT`;
- `OcrPage` constructor rejection of zero, boolean, non-integer pages and
  non-string/NUL text;
- service rejection of duplicate, descending, and over-limit valid page
  records, non-tuple results, and wrong result item types;
- page/block/total text resource limits and exact-boundary success;
- immutable exact public records and fixed safe errors;
- public package exports;
- AST dependency guards for service and fake adapter imports; and
- absence of OCR/model/network/filesystem/subprocess dependencies.

Relevant parser and ingestion unit suites run after focused GREEN. The existing
document-version integration suite verifies that OCR-produced
`ParsedDocument` values remain compatible with later chunking/persistence
contracts without a schema change. The complete project gate, Ruff, mypy, and
dependency check run before completion.

## 10. Acceptance mapping

| Task 012 criterion | Design evidence |
|---|---|
| Scanned PDF returns `OCR_REQUIRED` when disabled | Default `ocr=None`; only the exact typed condition may invoke fallback |
| OCR result preserves page numbers | `OcrPage.page` becomes `ParsedBlock.page`; gaps are retained and ordinals are independent |
| No OCR engine leaks into domain/service interfaces | Bytes-only `OcrPort`; service imports no adapter or engine package |
| Tests use fake OCR adapter | Deterministic `FakeOcrAdapter` is the only OCR implementation added |

## 11. Expected files

- Create `services/ingestion/ocr.py`.
- Modify `services/ingestion/__init__.py`.
- Create `adapters/ocr/__init__.py`.
- Create `adapters/ocr/fake.py`.
- Create `tests/unit/ingestion/test_ocr_flow.py`.
- Modify `docs/03-knowledge-system.md`.
- Create the corresponding Task 012 implementation plan under
  `docs/superpowers/plans/` after this design is approved.

No migration, dependency, parser-adapter implementation, domain, retrieval,
authorization, model, or Task 013 file is in scope.
