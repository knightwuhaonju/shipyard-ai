import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

import services.ingestion as ingestion
import services.ingestion.parser as parser_contract
from adapters.ocr import FakeOcrAdapter
from adapters.parsers import PdfParser, TxtParser
from services.ingestion import (
    DocumentFormat,
    OcrFallbackParser,
    OcrPage,
    OcrPort,
    ParsedBlockKind,
    ParserError,
    ParserErrorCode,
)
from tests.fixtures.parser_documents import (
    blank_pdf_bytes,
    encrypted_pdf_bytes,
    synthetic_pdf_bytes,
)


class _BadOcrPort:
    def __init__(self, result: object) -> None:
        self._result = result

    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]:
        del content
        return cast(tuple[OcrPage, ...], self._result)


class _FailingOcrPort:
    def __init__(self, error: RuntimeError) -> None:
        self._error = error

    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]:
        del content
        raise self._error


def _assert_ocr_result_error(
    result: object, code: ParserErrorCode, message: str
) -> None:
    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser(), ocr=_BadOcrPort(result)).parse(
            blank_pdf_bytes()
        )

    assert captured.value.code is code
    assert str(captured.value) == message
    assert captured.value.__cause__ is None


def _resolve_import_module(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = module_name.rpartition(".")[0].split(".")
    retained_parts = len(package_parts) - node.level + 1
    assert retained_parts > 0
    return ".".join(
        (*package_parts[:retained_parts], *(node.module or "").split("."))
    ).rstrip(".")


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def _assert_import_boundary(
    source: str,
    *,
    module_name: str,
    allowed_modules: set[str],
    allowed_targets: set[str],
    filename: str = "<ocr-boundary>",
) -> None:
    tree = ast.parse(source, filename=filename)
    imported_modules: set[str] = set()
    imported_targets: set[str] = set()
    bound_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                imported_targets.add(alias.name)
                bound_names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            resolved_module = _resolve_import_module(module_name, node)
            imported_modules.add(resolved_module)
            for alias in node.names:
                imported_targets.add(f"{resolved_module}.{alias.name}")
                bound_names.add(alias.asname or alias.name)

    assert imported_modules <= allowed_modules
    assert imported_targets <= allowed_targets

    forbidden_names = {
        "aiohttp",
        "anthropic",
        "auth",
        "authorization",
        "cohere",
        "database",
        "document_store",
        "fitz",
        "google",
        "httpx",
        "litellm",
        "mistralai",
        "ocrmypdf",
        "ollama",
        "openai",
        "os",
        "pathlib",
        "pdf2image",
        "persistence",
        "pypdf",
        "pytesseract",
        "repository",
        "requests",
        "retrieval",
        "socket",
        "sqlalchemy",
        "subprocess",
        "tensorflow",
        "torch",
        "transformers",
        "urllib",
    }
    referenced_names = bound_names | {
        qualified
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
        if (qualified := _qualified_name(node)) is not None
    }
    referenced_parts = {
        part
        for name in referenced_names
        for dotted_part in name.split(".")
        for part in {dotted_part.lower(), *dotted_part.lower().split("_")}
    }
    assert referenced_parts.isdisjoint(forbidden_names)


def _assert_ocr_service_imports(
    source: str, *, filename: str = "<ocr-service>"
) -> None:
    _assert_import_boundary(
        source,
        module_name="services.ingestion.ocr",
        allowed_modules={
            "__future__",
            "dataclasses",
            "services.ingestion.parser",
            "typing",
        },
        allowed_targets={
            "__future__.annotations",
            "dataclasses.dataclass",
            "services.ingestion.parser",
            "services.ingestion.parser.DocumentFormat",
            "services.ingestion.parser.ParsedBlock",
            "services.ingestion.parser.ParsedBlockKind",
            "services.ingestion.parser.ParsedDocument",
            "services.ingestion.parser.Parser",
            "services.ingestion.parser.ParserError",
            "services.ingestion.parser.ParserErrorCode",
            "services.ingestion.parser.normalize_block_text",
            "services.ingestion.parser.validate_source_bytes",
            "typing.Protocol",
            "typing.cast",
        },
        filename=filename,
    )


def _assert_fake_ocr_imports(
    source: str, *, filename: str = "<fake-ocr-adapter>"
) -> None:
    _assert_import_boundary(
        source,
        module_name="adapters.ocr.fake",
        allowed_modules={"services.ingestion.ocr"},
        allowed_targets={
            "services.ingestion.ocr.OcrPage",
            "services.ingestion.ocr.OcrPort",
        },
        filename=filename,
    )


def test_ocr_service_imports_remain_inside_the_pure_boundary() -> None:
    source_path = Path("services/ingestion/ocr.py")

    _assert_ocr_service_imports(
        source_path.read_text(encoding="utf-8"), filename=str(source_path)
    )


def test_fake_ocr_imports_only_the_service_contract() -> None:
    source_path = Path("adapters/ocr/fake.py")

    _assert_fake_ocr_imports(
        source_path.read_text(encoding="utf-8"), filename=str(source_path)
    )


@pytest.mark.parametrize(
    "source",
    [
        "from .document_store import DocumentStore",
        "from .. import retrieval as r",
        "from services import retrieval as r",
        "from services.ingestion import document_store as store",
        "pypdf.PdfReader(b'synthetic')",
        "from services.ingestion.parser import ParsedBlock as pypdf",
    ],
    ids=[
        "relative-document-store",
        "parent-relative-retrieval",
        "services-alias-retrieval",
        "ingestion-alias-document-store",
        "unimported-engine-name",
        "forbidden-import-alias",
    ],
)
def test_ocr_service_import_guard_rejects_dependency_bypass_syntax(
    source: str,
) -> None:
    with pytest.raises(AssertionError):
        _assert_ocr_service_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "from . import engine",
        "from ...services.ingestion.ocr import OcrPage",
        "from services.ingestion import ocr as contract",
        "from services.ingestion.ocr import OcrPage as openai",
    ],
    ids=[
        "relative-engine",
        "over-deep-relative-service",
        "parent-module-alias",
        "forbidden-import-alias",
    ],
)
def test_fake_ocr_import_guard_rejects_dependency_bypass_syntax(
    source: str,
) -> None:
    with pytest.raises(AssertionError):
        _assert_fake_ocr_imports(source)


def test_ingestion_public_surface_preserves_existing_and_exact_ocr_names() -> None:
    existing_public_names = {
        "DEFAULT_MAX_CHARS",
        "DocumentChunkConflictError",
        "DocumentConflictError",
        "DocumentFormat",
        "DocumentNotFoundError",
        "DocumentRepository",
        "DocumentRepositoryError",
        "DocumentStore",
        "DocumentStoreError",
        "DocumentVersionConflictError",
        "DocumentVersionNotFoundError",
        "ParsedBlock",
        "ParsedBlockKind",
        "ParsedDocument",
        "Parser",
        "ParserError",
        "ParserErrorCode",
        "StructuralChunker",
        "TableCells",
        "normalize_block_text",
        "normalize_table_cell",
        "render_table",
        "validate_source_bytes",
    }
    public_names = set(ingestion.__all__)

    assert existing_public_names <= public_names
    assert {name for name in public_names if name.startswith("Ocr")} == {
        "OcrFallbackParser",
        "OcrPage",
        "OcrPort",
    }
    assert ingestion.OcrFallbackParser is OcrFallbackParser
    assert ingestion.OcrPage is OcrPage
    assert ingestion.OcrPort is OcrPort


def test_textless_pdf_requires_ocr_before_task_012_fallback_exists() -> None:
    with pytest.raises(ParserError) as captured:
        PdfParser().parse(blank_pdf_bytes())

    assert captured.value.code is ParserErrorCode.OCR_REQUIRED
    assert str(captured.value) == "PDF has no extractable text layer"


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


def test_ocr_is_disabled_by_default() -> None:
    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser()).parse(blank_pdf_bytes())
    assert captured.value.code is ParserErrorCode.OCR_REQUIRED


def test_unexpected_ocr_adapter_programming_error_remains_visible() -> None:
    error = RuntimeError("synthetic adapter programming error")

    with pytest.raises(RuntimeError) as captured:
        OcrFallbackParser(PdfParser(), ocr=_FailingOcrPort(error)).parse(
            blank_pdf_bytes()
        )

    assert captured.value is error


def test_text_layer_pdf_bypasses_injected_ocr() -> None:
    fake = FakeOcrAdapter((OcrPage(page=1, text="must not run"),))
    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(synthetic_pdf_bytes())
    assert [block.page for block in parsed.blocks] == [1, 2]
    assert fake.received_contents == ()


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", ParserErrorCode.EMPTY_DOCUMENT),
        (encrypted_pdf_bytes(), ParserErrorCode.ENCRYPTED_DOCUMENT),
        (b"%PDF-1.4\nnot a PDF", ParserErrorCode.INVALID_DOCUMENT),
        (
            b"x" * (parser_contract.MAX_SOURCE_BYTES + 1),
            ParserErrorCode.RESOURCE_LIMIT,
        ),
    ],
    ids=["empty", "encrypted", "malformed", "resource-limit"],
)
def test_non_ocr_required_primary_errors_bypass_ocr(
    content: bytes, code: ParserErrorCode
) -> None:
    fake = FakeOcrAdapter((OcrPage(page=1, text="must not run"),))

    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser(), ocr=fake).parse(content)

    assert captured.value.code is code
    assert fake.received_contents == ()


def test_ocr_fallback_rejects_non_pdf_primary_parser() -> None:
    with pytest.raises(ValueError, match="^primary parser must use PDF format$"):
        OcrFallbackParser(TxtParser())


def test_blank_ocr_page_preserves_later_page_gap() -> None:
    fake = FakeOcrAdapter(
        (
            OcrPage(page=1, text=" \t\r\n "),
            OcrPage(page=3, text="  Synthetic third page  "),
        )
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(blank_pdf_bytes())

    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].ordinal == 0
    assert parsed.blocks[0].page == 3
    assert parsed.blocks[0].text == "Synthetic third page"


@pytest.mark.parametrize(
    "result",
    [[OcrPage(page=1, text="Synthetic page")], (object(),)],
    ids=["list-result", "wrong-item-type"],
)
def test_ocr_result_rejects_invalid_shapes_with_safe_error(result: object) -> None:
    _assert_ocr_result_error(
        result,
        ParserErrorCode.INVALID_DOCUMENT,
        "document cannot be parsed",
    )


@pytest.mark.parametrize(
    "pages",
    [
        (OcrPage(page=1, text="First"), OcrPage(page=1, text="Duplicate")),
        (OcrPage(page=2, text="Second"), OcrPage(page=1, text="First")),
    ],
    ids=["duplicate", "descending"],
)
def test_ocr_result_rejects_non_increasing_pages(
    pages: tuple[OcrPage, ...],
) -> None:
    _assert_ocr_result_error(
        pages,
        ParserErrorCode.INVALID_DOCUMENT,
        "document cannot be parsed",
    )


def test_ocr_result_rejects_page_above_parser_limit() -> None:
    pages = (
        OcrPage(page=parser_contract.MAX_PDF_PAGES + 1, text="Synthetic page"),
    )

    _assert_ocr_result_error(
        pages,
        ParserErrorCode.RESOURCE_LIMIT,
        "document exceeds parser resource limits",
    )


def test_ocr_result_allows_exact_block_count_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 2)
    fake = FakeOcrAdapter(
        (
            OcrPage(page=1, text="First"),
            OcrPage(page=2, text="Second"),
        )
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(blank_pdf_bytes())

    assert [block.text for block in parsed.blocks] == ["First", "Second"]


def test_ocr_result_rejects_block_count_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 1)
    pages = (
        OcrPage(page=1, text="First"),
        OcrPage(page=2, text="Second"),
    )

    _assert_ocr_result_error(
        pages,
        ParserErrorCode.RESOURCE_LIMIT,
        "document exceeds parser resource limits",
    )


def test_ocr_result_allows_exact_per_page_text_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_BLOCK_CHARS", 4)
    fake = FakeOcrAdapter((OcrPage(page=1, text="four"),))

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(blank_pdf_bytes())

    assert parsed.blocks[0].text == "four"


def test_ocr_result_rejects_per_page_text_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_BLOCK_CHARS", 4)

    _assert_ocr_result_error(
        (OcrPage(page=1, text="fives"),),
        ParserErrorCode.RESOURCE_LIMIT,
        "document exceeds parser resource limits",
    )


def test_ocr_result_allows_exact_total_text_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_TOTAL_TEXT_CHARS", 5)
    fake = FakeOcrAdapter(
        (OcrPage(page=1, text="ab"), OcrPage(page=2, text="cde"))
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(blank_pdf_bytes())

    assert [block.text for block in parsed.blocks] == ["ab", "cde"]


def test_ocr_result_rejects_total_text_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_TOTAL_TEXT_CHARS", 5)

    _assert_ocr_result_error(
        (OcrPage(page=1, text="ab"), OcrPage(page=2, text="cdef")),
        ParserErrorCode.RESOURCE_LIMIT,
        "document exceeds parser resource limits",
    )


@pytest.mark.parametrize(
    "pages",
    [(), (OcrPage(page=1, text=" \t\r\n "),)],
    ids=["empty", "all-blank"],
)
def test_ocr_result_rejects_no_retained_text(
    pages: tuple[OcrPage, ...],
) -> None:
    _assert_ocr_result_error(
        pages,
        ParserErrorCode.EMPTY_DOCUMENT,
        "document contains no parseable content",
    )


def test_ocr_result_rejects_invalid_text_with_safe_error() -> None:
    page = OcrPage(page=1, text="Synthetic page")
    object.__setattr__(page, "text", "invalid\x00text")

    _assert_ocr_result_error(
        (page,),
        ParserErrorCode.INVALID_DOCUMENT,
        "document cannot be parsed",
    )


@pytest.mark.parametrize("page_value", [True, 1.0, "1"])
def test_ocr_result_rejects_forged_non_integer_page_with_safe_error(
    page_value: object,
) -> None:
    page = OcrPage(page=1, text="Synthetic page")
    object.__setattr__(page, "page", page_value)

    _assert_ocr_result_error(
        (page,),
        ParserErrorCode.INVALID_DOCUMENT,
        "document cannot be parsed",
    )


@pytest.mark.parametrize("pages", [[], (object(),)])
def test_fake_ocr_rejects_invalid_configured_pages(pages: object) -> None:
    with pytest.raises(ValueError, match="^pages must be a tuple of OcrPage$"):
        FakeOcrAdapter(cast(tuple[OcrPage, ...], pages))


def test_fake_ocr_returns_configured_pages_and_immutable_history() -> None:
    pages = (OcrPage(page=2, text="Synthetic page"),)
    fake = FakeOcrAdapter(pages)

    returned = fake.recognize_pdf(b"first")
    first_history = fake.received_contents
    fake.recognize_pdf(b"second")

    assert returned is pages
    assert type(first_history) is tuple
    assert first_history == (b"first",)
    assert fake.received_contents == (b"first", b"second")


def test_ocr_page_is_an_exact_immutable_port_record() -> None:
    page = OcrPage(page=3, text="  synthetic OCR text  ")

    assert type(page) is OcrPage
    assert page.page == 3
    assert page.text == "  synthetic OCR text  "
    with pytest.raises(FrozenInstanceError):
        page.page = 4  # type: ignore[misc]


def _accept_port(port: OcrPort) -> OcrPort:
    return port


@pytest.mark.parametrize("page", [0, -1, True, 1.0, "1"])
def test_ocr_page_rejects_invalid_page(page: object) -> None:
    with pytest.raises(ValueError, match="^page must be a positive integer$"):
        OcrPage(page=cast(int, page), text="synthetic")


@pytest.mark.parametrize("text", [None, b"text", "bad\x00text"])
def test_ocr_page_rejects_invalid_text(text: object) -> None:
    with pytest.raises(ValueError, match="^text must be a string without NUL$"):
        OcrPage(page=1, text=cast(str, text))


def test_ocr_page_accepts_blank_processed_text() -> None:
    page = OcrPage(page=1, text="")

    assert page.text == ""
