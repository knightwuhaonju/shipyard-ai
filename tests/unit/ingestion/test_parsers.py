"""Tests for the immutable, parser-neutral ingestion contract."""

import ast
import socket
import struct
import traceback
import warnings
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile

import pytest
from pypdf.errors import FileNotDecryptedError, LimitReachedError, PdfStreamError

import services.ingestion.parser as parser_contract
from adapters.parsers import (
    DocxParser,
    MarkdownParser,
    PdfParser,
    TxtParser,
    XlsxParser,
)
from adapters.parsers._common import validate_ooxml_archive
from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    Parser,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    normalize_table_cell,
    render_table,
    validate_source_bytes,
)
from tests.fixtures.parser_documents import (
    blank_docx_bytes,
    blank_pdf_bytes,
    blank_xlsx_bytes,
    encrypted_pdf_bytes,
    heading_hierarchy_docx_bytes,
    merged_table_docx_bytes,
    pdf_with_blank_middle_page_bytes,
    synthetic_docx_bytes,
    synthetic_markdown_bytes,
    synthetic_pdf_bytes,
    synthetic_txt_bytes,
    synthetic_xlsx_bytes,
    trailing_blank_xlsx_bytes,
)

_PARSER_ERROR_MESSAGES = {
    ParserErrorCode.INVALID_DOCUMENT: "document cannot be parsed",
    ParserErrorCode.UNSUPPORTED_ENCODING: "document text encoding is unsupported",
    ParserErrorCode.ENCRYPTED_DOCUMENT: "encrypted documents are unsupported",
    ParserErrorCode.RESOURCE_LIMIT: "document exceeds parser resource limits",
    ParserErrorCode.EMPTY_DOCUMENT: "document contains no parseable content",
    ParserErrorCode.OCR_REQUIRED: "PDF has no extractable text layer",
}

_TEXT_PARSER_FACTORIES: tuple[Callable[[], Parser], ...] = (
    TxtParser,
    MarkdownParser,
)


def _zip_bytes(members: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, content in members:
                archive.writestr(name, content)
    return output.getvalue()


def _zip_with_declared_sizes(
    *, uncompressed_size: int, compressed_size: int | None = None
) -> bytes:
    content = bytearray(_zip_bytes((("word/document.xml", b"x"),)))
    central_directory = content.index(b"PK\x01\x02")
    if compressed_size is not None:
        struct.pack_into("<I", content, central_directory + 20, compressed_size)
    struct.pack_into("<I", content, central_directory + 24, uncompressed_size)
    return bytes(content)


def _docx_with_encrypted_content_types() -> bytes:
    content = bytearray(synthetic_docx_bytes())
    central_directory = content.index(b"PK\x01\x02")
    while content[central_directory : central_directory + 4] == b"PK\x01\x02":
        name_length = struct.unpack_from("<H", content, central_directory + 28)[0]
        extra_length = struct.unpack_from("<H", content, central_directory + 30)[0]
        comment_length = struct.unpack_from("<H", content, central_directory + 32)[0]
        name_start = central_directory + 46
        name = bytes(content[name_start : name_start + name_length])
        if name == b"[Content_Types].xml":
            flag_bits = struct.unpack_from("<H", content, central_directory + 8)[0]
            struct.pack_into("<H", content, central_directory + 8, flag_bits | 0x1)
            return bytes(content)
        central_directory = (
            name_start + name_length + extra_length + comment_length
        )
    raise AssertionError("synthetic DOCX lacks [Content_Types].xml")


def _docx_with_external_relationship() -> bytes:
    source = BytesIO(synthetic_docx_bytes())
    output = BytesIO()
    relationship = (
        b'<Relationship Id="rExternal" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'relationships/hyperlink" Target="https://example.invalid/drawing" '
        b'TargetMode="External"/>'
    )
    relationship_path = "word/_rels/document.xml.rels"
    with ZipFile(source) as source_archive, ZipFile(output, "w") as target_archive:
        for member in source_archive.infolist():
            content = source_archive.read(member)
            if member.filename == relationship_path:
                content = content.replace(
                    b"</Relationships>", relationship + b"</Relationships>"
                )
            target_archive.writestr(member, content)
    return output.getvalue()


def _xlsx_with_underreported_dimension() -> bytes:
    source = BytesIO(synthetic_xlsx_bytes())
    output = BytesIO()
    worksheet_path = "xl/worksheets/sheet1.xml"
    with ZipFile(source) as source_archive, ZipFile(output, "w") as target_archive:
        for member in source_archive.infolist():
            content = source_archive.read(member)
            if member.filename == worksheet_path:
                dimension_start = content.index(b"<dimension ")
                dimension_end = content.index(b"/>", dimension_start) + 2
                content = (
                    content[:dimension_start]
                    + b'<dimension ref="A1"/>'
                    + content[dimension_end:]
                )
            target_archive.writestr(member, content)
    return output.getvalue()


class _WorksheetStub:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self.title = "Stub"
        self._rows = rows
        self.reset_called = False

    def reset_dimensions(self) -> None:
        self.reset_called = True

    def iter_rows(self, *, values_only: bool) -> tuple[tuple[object, ...], ...]:
        if values_only is not True:
            raise AssertionError("XLSX parser did not request values_only rows")
        return self._rows


class _WorkbookStub:
    def __init__(self, worksheet: _WorksheetStub) -> None:
        self.worksheets = [worksheet]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ExplodingSequence[T]:
    def __init__(self, values: tuple[T, ...], message: str) -> None:
        self._values = values
        self._message = message

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[T]:
        yield from self._values
        raise AssertionError(self._message)


class _PdfContentsStub:
    def __init__(self, data: bytes | Exception) -> None:
        self._data = data
        self.get_data_calls = 0

    def get_data(self) -> bytes:
        self.get_data_calls += 1
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class _PdfPageStub:
    def __init__(self, text: str, contents: _PdfContentsStub | None = None) -> None:
        self._text = text
        self._contents = contents
        self.extract_text_calls = 0

    def get_contents(self) -> _PdfContentsStub | None:
        return self._contents

    def extract_text(self) -> str:
        if self._contents is not None and self._contents.get_data_calls != 1:
            raise AssertionError("PDF content stream was not decoded exactly once")
        self.extract_text_calls += 1
        return self._text


class _PdfReaderStub:
    def __init__(self, pages: object, *, is_encrypted: bool = False) -> None:
        self.pages = pages
        self.is_encrypted = is_encrypted


def _assert_parser_error(
    raised: pytest.ExceptionInfo[ParserError], code: ParserErrorCode
) -> None:
    assert raised.value.code is code
    assert str(raised.value) == _PARSER_ERROR_MESSAGES[code]
    assert raised.value.__cause__ is None


def _paragraph(**changes: object) -> ParsedBlock:
    values: dict[str, object] = {
        "ordinal": 0,
        "kind": ParsedBlockKind.PARAGRAPH,
        "text": "Pump installation requirements",
    }
    values.update(changes)
    return ParsedBlock(**values)  # type: ignore[arg-type]


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


def test_parser_adapters_respect_architecture_and_common_surface() -> None:
    allowed_import_roots = {
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
    denied_import_prefixes = {
        "adapters.ocr",
        "anthropic",
        "cohere",
        "fitz",
        "google.generativeai",
        "httpx",
        "mistralai",
        "ocrmypdf",
        "openai",
        "pdf2image",
        "pytesseract",
        "requests",
        "services.retrieval",
        "socket",
        "sqlalchemy",
        "urllib",
    }
    imported_modules: set[str] = set()
    non_relative_roots: set[str] = set()

    for path in sorted(Path("adapters/parsers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imported_modules.add(name.name)
                    non_relative_roots.add(name.name.split(".", maxsplit=1)[0])
            # __future__ selects compiler behavior; it is not a runtime dependency.
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                if node.level:
                    package_parts = ["adapters", "parsers"]
                    parent_count = node.level - 1
                    relative_parts = package_parts[: len(package_parts) - parent_count]
                    if node.module is not None:
                        relative_parts.extend(node.module.split("."))
                    imported_modules.add(".".join(relative_parts))
                elif node.module is not None:
                    imported_modules.add(node.module)
                    non_relative_roots.add(node.module.split(".", maxsplit=1)[0])

    assert non_relative_roots <= allowed_import_roots
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in denied_import_prefixes
    )

    parsers: tuple[Parser, ...] = (
        TxtParser(),
        MarkdownParser(),
        DocxParser(),
        XlsxParser(),
        PdfParser(),
    )
    sources = (
        synthetic_txt_bytes(),
        synthetic_markdown_bytes(),
        synthetic_docx_bytes(),
        synthetic_xlsx_bytes(),
        synthetic_pdf_bytes(),
    )
    formats = (
        DocumentFormat.TXT,
        DocumentFormat.MARKDOWN,
        DocumentFormat.DOCX,
        DocumentFormat.XLSX,
        DocumentFormat.PDF,
    )

    for parser, source, format_ in zip(parsers, sources, formats, strict=True):
        parsed = parser.parse(source)

        assert parser.format is format_
        assert isinstance(parsed, ParsedDocument)
        assert parsed.format is format_
        assert parsed.blocks


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (ParserErrorCode.INVALID_DOCUMENT, "document cannot be parsed"),
        (
            ParserErrorCode.UNSUPPORTED_ENCODING,
            "document text encoding is unsupported",
        ),
        (ParserErrorCode.ENCRYPTED_DOCUMENT, "encrypted documents are unsupported"),
        (ParserErrorCode.RESOURCE_LIMIT, "document exceeds parser resource limits"),
        (ParserErrorCode.EMPTY_DOCUMENT, "document contains no parseable content"),
        (ParserErrorCode.OCR_REQUIRED, "PDF has no extractable text layer"),
    ],
)
def test_parser_error_has_typed_code_and_fixed_message(
    code: ParserErrorCode, message: str
) -> None:
    error = ParserError(code)

    assert error.code is code
    assert str(error) == message


def test_parser_error_rejects_non_exact_error_code() -> None:
    with pytest.raises(TypeError, match="^code must be a ParserErrorCode$"):
        ParserError("invalid_document")  # type: ignore[arg-type]


class _IntSubclass(int):
    pass


class _StringSubclass(str):
    pass


class _TupleSubclass(tuple[object, ...]):
    pass


@pytest.mark.parametrize(
    "changes",
    [
        {"ordinal": _IntSubclass(0)},
        {"kind": Mock(spec=ParsedBlockKind)},
        {"text": _StringSubclass("Pump installation requirements")},
        {"structural_path": _TupleSubclass(("Equipment",))},
        {"structural_path": (_StringSubclass("Equipment"),)},
        {"page": _IntSubclass(1)},
        {"sheet": _StringSubclass("Equipment")},
    ],
)
def test_parsed_block_requires_exact_scalar_and_path_types(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _paragraph(**changes)


@pytest.mark.parametrize(
    "table",
    [
        _TupleSubclass((("item",),)),
        (_TupleSubclass(("item",)),),
        ((_StringSubclass("item"),),),
    ],
)
def test_parsed_block_requires_exact_table_container_and_cell_types(
    table: object,
) -> None:
    with pytest.raises(ValueError):
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text="item",
            table=table,  # type: ignore[arg-type]
        )


class _ParsedBlockSubclass(ParsedBlock):
    pass


@pytest.mark.parametrize("invalid_field", ["format", "blocks", "block"])
def test_parsed_document_requires_exact_field_and_block_types(
    invalid_field: str,
) -> None:
    block: ParsedBlock = _paragraph()
    format_: object = DocumentFormat.TXT
    blocks: object = (block,)
    if invalid_field == "format":
        format_ = Mock(spec=DocumentFormat)
    elif invalid_field == "blocks":
        blocks = _TupleSubclass((block,))
    else:
        blocks = (
            _ParsedBlockSubclass(
                ordinal=0,
                kind=ParsedBlockKind.PARAGRAPH,
                text="Pump installation requirements",
            ),
        )

    with pytest.raises(ValueError):
        ParsedDocument(
            format=format_,  # type: ignore[arg-type]
            blocks=blocks,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("ordinal", [True, -1, 1.5, "0"])
def test_parsed_block_rejects_invalid_ordinal(ordinal: object) -> None:
    with pytest.raises(ValueError, match="^ordinal must be a non-negative integer$"):
        _paragraph(ordinal=ordinal)


def test_parsed_document_requires_contiguous_ordinals() -> None:
    block = _paragraph(ordinal=1)

    with pytest.raises(ValueError, match="^blocks must have contiguous ordinals$"):
        ParsedDocument(format=DocumentFormat.TXT, blocks=(block,))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("text", " \t\n", "text must be non-blank"),
        ("structural_path", ("Equipment", " "), "structural_path must be non-blank"),
        ("sheet", "\t", "sheet must be non-blank"),
    ],
)
def test_parsed_block_rejects_blank_content(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        _paragraph(**{field: value})


@pytest.mark.parametrize("page", [True, 0, -1, 1.5, "1"])
def test_parsed_block_rejects_invalid_page(page: object) -> None:
    with pytest.raises(ValueError, match="^page must be a positive integer$"):
        _paragraph(page=page)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": ParsedBlockKind.PAGE},
        {
            "kind": ParsedBlockKind.PAGE,
            "page": 1,
            "table": (("item",),),
        },
    ],
)
def test_page_blocks_enforce_page_only_metadata(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _paragraph(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": ParsedBlockKind.TABLE},
        {"kind": ParsedBlockKind.TABLE, "page": 1, "table": (("item",),)},
        {"kind": ParsedBlockKind.TABLE, "table": (("item",), ("pump", "2"))},
        {"kind": ParsedBlockKind.TABLE, "table": (("",),)},
        {
            "kind": ParsedBlockKind.TABLE,
            "table": (("item",),),
            "text": "not canonical",
        },
    ],
)
def test_table_blocks_enforce_canonical_table_invariants(
    changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        _paragraph(**changes)


def test_non_table_block_rejects_cells() -> None:
    with pytest.raises(ValueError, match="^table is only allowed for TABLE blocks$"):
        _paragraph(table=(("item",),))


def test_only_xlsx_documents_allow_sheet_metadata() -> None:
    block = _paragraph(sheet="Bill of Materials")

    with pytest.raises(ValueError, match="^sheet is only allowed for XLSX documents$"):
        ParsedDocument(format=DocumentFormat.MARKDOWN, blocks=(block,))


def test_parsed_document_rejects_empty_blocks() -> None:
    with pytest.raises(ValueError, match="^blocks must not be empty$"):
        ParsedDocument(format=DocumentFormat.TXT, blocks=())


def test_normalizers_normalize_newlines_without_unicode_compatibility_changes() -> None:
    assert normalize_block_text("  \ufb02ange  \r\nDeck\t \rSteel  ") == (
        "\ufb02ange\nDeck\nSteel"
    )
    assert normalize_table_cell("  \ufb02ange\r\n\tline  ") == "\ufb02ange line"


def test_render_table_canonicalizes_whitespace_and_trailing_empty_edges() -> None:
    cells = (
        (" Item ", "Qty", ""),
        ("Pump", "", ""),
        ("", "2", ""),
        ("", "", ""),
    )

    assert render_table(cells) == "Item\tQty\nPump\t\n\t2"


def test_validate_source_bytes_rejects_invalid_empty_and_oversized_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ParserError) as invalid:
        validate_source_bytes("not bytes")  # type: ignore[arg-type]
    assert invalid.value.code is ParserErrorCode.INVALID_DOCUMENT

    with pytest.raises(ParserError) as empty:
        validate_source_bytes(b"")
    assert empty.value.code is ParserErrorCode.EMPTY_DOCUMENT

    monkeypatch.setattr("services.ingestion.parser.MAX_SOURCE_BYTES", 2)
    with pytest.raises(ParserError) as oversized:
        validate_source_bytes(b"abc")
    assert oversized.value.code is ParserErrorCode.RESOURCE_LIMIT


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

    assert [block.ordinal for block in parsed.blocks] == list(range(len(parsed.blocks)))
    assert parsed.blocks[-1].kind is ParsedBlockKind.TABLE
    assert parsed.blocks[-1].structural_path == ("合成规范", "泵组")
    assert parsed.blocks[-1].table == (("项目", "数量"), ("泵", "2"))


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
    assert [block.ordinal for block in parsed.blocks] == list(range(5))
    assert parsed.blocks[-1].structural_path == (
        "合成船级规则",
        "机械系统",
        "泵组",
    )
    assert parsed.blocks[-1].table == (("检查项", "结果"), ("轴封", "合格"))


def test_docx_parser_keeps_title_as_root_and_replaces_shallower_headings() -> None:
    parsed = DocxParser().parse(heading_hierarchy_docx_bytes())

    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.TITLE,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
    ]
    assert [block.structural_path for block in parsed.blocks] == [
        ("根标题",),
        ("根标题", "初始系统"),
        ("根标题", "初始系统", "初始设备"),
        ("根标题", "替换系统"),
        ("根标题", "替换系统", "九级主题"),
        ("根标题", "替换系统", "八级替换"),
        ("根标题", "替换系统", "八级替换"),
    ]


def test_docx_parser_represents_merged_cells_once_in_rectangular_table() -> None:
    parsed = DocxParser().parse(merged_table_docx_bytes())

    assert parsed.blocks[0].table == (("检查项", ""), ("轴封", "合格"))


def test_ooxml_preflight_rejects_invalid_archive_with_safe_typed_error() -> None:
    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(b"not a ZIP archive")

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize(
    "members",
    [
        (("word/document.xml", b"first"), ("word/document.xml", b"second")),
        (("word/document.xml", b"first"), ("word\\document.xml", b"second")),
    ],
)
def test_ooxml_preflight_rejects_duplicate_normalized_names(
    members: tuple[tuple[str, bytes], ...],
) -> None:
    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(_zip_bytes(members))

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize("name", ["/absolute.xml", "../escape.xml", "..\\escape.xml"])
def test_ooxml_preflight_rejects_absolute_and_traversal_paths(name: str) -> None:
    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(_zip_bytes(((name, b"unsafe"),)))

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


def test_ooxml_preflight_rejects_too_many_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_ARCHIVE_ENTRIES", 1)

    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(_zip_bytes((("one.xml", b"1"), ("two.xml", b"2"))))

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_ooxml_preflight_rejects_declared_uncompressed_total_over_limit() -> None:
    content = _zip_with_declared_sizes(
        uncompressed_size=parser_contract.MAX_ARCHIVE_UNCOMPRESSED_BYTES + 1
    )

    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(content)

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_ooxml_preflight_rejects_declared_compression_ratio_over_limit() -> None:
    content = _zip_with_declared_sizes(
        uncompressed_size=parser_contract.MAX_ARCHIVE_COMPRESSION_RATIO + 1,
        compressed_size=1,
    )

    with pytest.raises(ParserError) as raised:
        validate_ooxml_archive(content)

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


@pytest.mark.parametrize(
    ("parser", "library_target"),
    [
        (DocxParser(), "adapters.parsers.docx.Document"),
        (XlsxParser(), "openpyxl.load_workbook"),
    ],
)
def test_ooxml_preflight_rejects_unsupported_compression_before_library_parse(
    parser: Parser,
    library_target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_BZIP2) as archive:
        archive.writestr("[Content_Types].xml", b"synthetic")

    def fail_library(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("format library received unsupported ZIP compression")

    monkeypatch.setattr(library_target, fail_library)

    with pytest.raises(ParserError) as raised:
        parser.parse(output.getvalue())

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


def test_docx_parser_translates_malformed_package_to_safe_typed_error() -> None:
    malformed = _zip_bytes((("[Content_Types].xml", b"<broken"),))

    with pytest.raises(ParserError) as raised:
        DocxParser().parse(malformed)

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


def test_docx_parser_rejects_encrypted_zip_member_with_safe_typed_error() -> None:
    with pytest.raises(ParserError) as raised:
        DocxParser().parse(_docx_with_encrypted_content_types())

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


def test_docx_parser_rejects_blank_paragraphs_and_tables_as_empty() -> None:
    with pytest.raises(ParserError) as raised:
        DocxParser().parse(blank_docx_bytes())

    _assert_parser_error(raised, ParserErrorCode.EMPTY_DOCUMENT)


def test_docx_parser_does_not_follow_http_relationships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("DOCX parser attempted outbound network access")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)

    parsed = DocxParser().parse(_docx_with_external_relationship())

    assert parsed.blocks[0].text == "合成船级规则"


def test_xlsx_parser_returns_one_whole_table_per_nonempty_sheet() -> None:
    parsed = XlsxParser().parse(synthetic_xlsx_bytes())

    assert parsed.format is DocumentFormat.XLSX
    assert [block.sheet for block in parsed.blocks] == ["泵组", "材料"]
    assert [block.ordinal for block in parsed.blocks] == [0, 1]
    assert all(block.kind is ParsedBlockKind.TABLE for block in parsed.blocks)
    assert parsed.blocks[0].structural_path == ("泵组",)
    assert "=1+1" in parsed.blocks[0].text
    assert "TRUE" in parsed.blocks[0].text


def test_xlsx_parser_converts_types_and_preserves_interior_empty_cells() -> None:
    parsed = XlsxParser().parse(synthetic_xlsx_bytes())

    assert parsed.blocks[0].table == (
        ("项目", "计算", "日期", "通过", "备注", "状态"),
        ("轴封", "=1+1", "2026-08-19", "TRUE", "", "待复核"),
        (
            "泵轴",
            "1.25",
            "2026-08-19T14:30:45",
            "FALSE",
            "06:15:30",
            "完成",
        ),
    )
    assert parsed.blocks[1].table == (("材料", "数量"), ("钢板", "12"))


def test_xlsx_parser_trims_only_trailing_empty_rows_and_columns() -> None:
    parsed = XlsxParser().parse(trailing_blank_xlsx_bytes())

    assert parsed.blocks[0].table == (
        ("项目", "数量", "备注"),
        ("泵", "2", ""),
    )


def test_xlsx_parser_skips_all_blank_sheets_and_rejects_empty_workbook() -> None:
    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(blank_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.EMPTY_DOCUMENT)


def test_xlsx_parser_ignores_underreported_worksheet_dimension() -> None:
    parsed = XlsxParser().parse(_xlsx_with_underreported_dimension())

    assert parsed.blocks[0].table is not None
    assert parsed.blocks[0].table[-1] == (
        "泵轴",
        "1.25",
        "2026-08-19T14:30:45",
        "FALSE",
        "06:15:30",
        "完成",
    )


def test_xlsx_parser_uses_safe_load_flags_values_only_and_closes_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worksheet = _WorksheetStub((("item", "qty"), ("pump", 2)))
    workbook = _WorkbookStub(worksheet)
    received_options: dict[str, object] = {}

    def fake_load_workbook(source: object, **options: object) -> _WorkbookStub:
        assert isinstance(source, BytesIO)
        received_options.update(options)
        return workbook

    monkeypatch.setattr("openpyxl.load_workbook", fake_load_workbook)

    parsed = XlsxParser().parse(synthetic_xlsx_bytes())

    assert parsed.blocks[0].table == (("item", "qty"), ("pump", "2"))
    assert received_options == {
        "read_only": True,
        "data_only": False,
        "keep_links": False,
        "keep_vba": False,
    }
    assert worksheet.reset_called is True
    assert workbook.closed is True


def test_xlsx_parser_closes_workbook_when_parsing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worksheet = _WorksheetStub((("item",),))
    workbook = _WorkbookStub(worksheet)
    monkeypatch.setattr("openpyxl.load_workbook", lambda *_args, **_kwargs: workbook)
    monkeypatch.setattr(parser_contract, "MAX_TABLE_ROWS", 0)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(synthetic_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)
    assert workbook.closed is True


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", ParserErrorCode.EMPTY_DOCUMENT),
        (_zip_bytes((("../escape.xml", b"unsafe"),)), ParserErrorCode.INVALID_DOCUMENT),
    ],
    ids=["empty-source", "unsafe-archive"],
)
def test_xlsx_parser_validates_source_and_archive_before_openpyxl(
    content: bytes,
    code: ParserErrorCode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("openpyxl received unsafe source bytes")

    monkeypatch.setattr("openpyxl.load_workbook", fail_load)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(content)

    _assert_parser_error(raised, code)


@pytest.mark.parametrize("content", ["workbook.xlsx", BytesIO(b"workbook")])
def test_xlsx_parser_rejects_non_bytes_before_openpyxl(
    content: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("openpyxl received a non-bytes parser input")

    monkeypatch.setattr("openpyxl.load_workbook", fail_load)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(content)  # type: ignore[arg-type]

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize(
    ("limit", "value"),
    [
        ("MAX_TABLE_ROWS", 2),
        ("MAX_TABLE_COLUMNS", 5),
        ("MAX_TABLE_CELLS", 17),
    ],
)
def test_xlsx_parser_enforces_table_limits_during_iteration(
    limit: str,
    value: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, limit, value)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(synthetic_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_xlsx_parser_accepts_exact_table_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_TABLE_ROWS", 3)
    monkeypatch.setattr(parser_contract, "MAX_TABLE_COLUMNS", 6)
    monkeypatch.setattr(parser_contract, "MAX_TABLE_CELLS", 18)

    parsed = XlsxParser().parse(synthetic_xlsx_bytes())

    assert [block.sheet for block in parsed.blocks] == ["泵组", "材料"]


def test_xlsx_parser_translates_malformed_workbook_to_safe_typed_error() -> None:
    malformed = _zip_bytes((("[Content_Types].xml", b"<broken"),))

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(malformed)

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


def test_xlsx_parser_does_not_make_network_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("XLSX parser attempted outbound network access")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)

    parsed = XlsxParser().parse(synthetic_xlsx_bytes())

    assert parsed.blocks[0].sheet == "泵组"


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


def test_pdf_parser_preserves_page_gap_when_middle_page_is_blank() -> None:
    parsed = PdfParser().parse(pdf_with_blank_middle_page_bytes())

    assert [block.page for block in parsed.blocks] == [1, 3]
    assert [block.text for block in parsed.blocks] == [
        "First text page",
        "Third text page",
    ]


def test_pdf_parser_rejects_encrypted_pdf_without_calling_decrypt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_decrypt(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PDF parser attempted password decryption")

    monkeypatch.setattr("pypdf.PdfReader.decrypt", fail_decrypt)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(encrypted_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.ENCRYPTED_DOCUMENT)


def test_pdf_parser_translates_malformed_pdf_to_safe_typed_error() -> None:
    with pytest.raises(ParserError) as raised:
        PdfParser().parse(b"%PDF-1.4\nmalformed synthetic object")

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", ParserErrorCode.EMPTY_DOCUMENT),
        ("document.pdf", ParserErrorCode.INVALID_DOCUMENT),
        (BytesIO(b"%PDF"), ParserErrorCode.INVALID_DOCUMENT),
    ],
    ids=["empty", "path-string", "byte-stream"],
)
def test_pdf_parser_validates_bytes_before_pypdf(
    content: object,
    code: ParserErrorCode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_reader(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pypdf received invalid parser input")

    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", fail_reader)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(content)  # type: ignore[arg-type]

    _assert_parser_error(raised, code)


def test_pdf_parser_uses_strict_in_memory_reader_and_decodes_before_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = _PdfContentsStub(b"BT (Stub page) Tj ET")
    page = _PdfPageStub("Stub page", contents)
    reader = _PdfReaderStub((page,))
    received_bytes: bytes | None = None

    def fake_reader(source: object, *, strict: bool) -> _PdfReaderStub:
        nonlocal received_bytes
        assert isinstance(source, BytesIO)
        received_bytes = source.getvalue()
        assert strict is True
        return reader

    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", fake_reader)

    parsed = PdfParser().parse(synthetic_pdf_bytes())

    assert received_bytes == synthetic_pdf_bytes()
    assert parsed.blocks[0].text == "Stub page"
    assert contents.get_data_calls == 1
    assert page.extract_text_calls == 1


def test_pdf_parser_checks_page_count_before_page_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UniteratedPages:
        def __len__(self) -> int:
            return 2

        def __iter__(self) -> object:
            raise AssertionError("PDF pages were iterated beyond the declared limit")

    reader = _PdfReaderStub(UniteratedPages())
    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", lambda *_a, **_k: reader)
    monkeypatch.setattr(parser_contract, "MAX_PDF_PAGES", 1)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_pdf_parser_limits_decoded_page_stream_before_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = _PdfContentsStub(b"1234")
    page = _PdfPageStub("must not be extracted", contents)
    reader = _PdfReaderStub((page,))
    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", lambda *_a, **_k: reader)
    monkeypatch.setattr(parser_contract, "MAX_PDF_PAGE_STREAM_BYTES", 3)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)
    assert contents.get_data_calls == 1
    assert page.extract_text_calls == 0


def test_pdf_parser_accepts_exact_page_and_stream_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, "MAX_PDF_PAGES", 2)
    monkeypatch.setattr(parser_contract, "MAX_PDF_PAGE_STREAM_BYTES", 49)

    parsed = PdfParser().parse(synthetic_pdf_bytes())

    assert [block.page for block in parsed.blocks] == [1, 2]


def test_pdf_parser_rejects_nul_extracted_text_with_safe_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pypdf._page.PageObject.extract_text", lambda _page: "bad\x00")

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize(
    ("limit", "value"),
    [("MAX_BLOCK_CHARS", 10), ("MAX_TOTAL_TEXT_CHARS", 20)],
)
def test_pdf_parser_translates_output_character_limits(
    limit: str,
    value: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_contract, limit, value)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PdfStreamError("sensitive stream details"), ParserErrorCode.INVALID_DOCUMENT),
        (
            FileNotDecryptedError("sensitive encryption details"),
            ParserErrorCode.ENCRYPTED_DOCUMENT,
        ),
        (
            LimitReachedError("sensitive resource details"),
            ParserErrorCode.RESOURCE_LIMIT,
        ),
    ],
)
def test_pdf_parser_translates_expected_pypdf_errors_without_leaking_details(
    error: Exception,
    code: ParserErrorCode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_reader(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", fail_reader)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, code)
    formatted = "".join(
        traceback.format_exception(
            type(raised.value), raised.value, raised.value.__traceback__
        )
    )
    assert str(error) not in formatted


def test_pdf_parser_does_not_swallow_unexpected_extraction_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenPage:
        def get_contents(self) -> None:
            return None

        def extract_text(self) -> str:
            raise ValueError("programmer error")

    reader = _PdfReaderStub((BrokenPage(),))
    monkeypatch.setattr("adapters.parsers.pdf.PdfReader", lambda *_a, **_k: reader)

    with pytest.raises(ValueError, match="^programmer error$"):
        PdfParser().parse(synthetic_pdf_bytes())


def test_pdf_adapter_imports_no_ocr_rendering_model_or_io_subsystems() -> None:
    tree = ast.parse(Path("adapters/parsers/pdf.py").read_text(encoding="utf-8"))
    imports = {
        name.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    forbidden_prefixes = (
        "adapters.ocr",
        "fitz",
        "httpx",
        "ocrmypdf",
        "pdf2image",
        "pytesseract",
        "requests",
        "services.model_gateway",
        "services.retrieval",
        "sqlalchemy",
        "urllib",
    )

    assert imports <= {
        "__future__",
        "_common",
        "io",
        "pypdf",
        "pypdf.errors",
        "services.ingestion",
        "services.ingestion.parser",
    }
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imports
        for prefix in forbidden_prefixes
    )


def test_markdown_parser_recognizes_setext_headings() -> None:
    parsed = MarkdownParser().parse(
        "合成规范\n====\n\n泵组\n----\n\n检查轴封。".encode()
    )

    assert [(block.kind, block.structural_path) for block in parsed.blocks] == [
        (ParsedBlockKind.HEADING, ("合成规范",)),
        (ParsedBlockKind.HEADING, ("合成规范", "泵组")),
        (ParsedBlockKind.PARAGRAPH, ("合成规范", "泵组")),
    ]


def test_markdown_parser_accepts_uniform_setext_delimiters() -> None:
    parsed = MarkdownParser().parse(
        "文档\n===\n\n泵组\n---\n\n检查轴封。".encode()
    )

    assert [(block.kind, block.structural_path) for block in parsed.blocks] == [
        (ParsedBlockKind.HEADING, ("文档",)),
        (ParsedBlockKind.HEADING, ("文档", "泵组")),
        (ParsedBlockKind.PARAGRAPH, ("文档", "泵组")),
    ]


def test_markdown_parser_keeps_mixed_setext_delimiter_as_paragraph_text() -> None:
    parsed = MarkdownParser().parse("文档\n===\n\n不是标题\n=-=\n\n## 泵组".encode())

    assert [
        (block.kind, block.text, block.structural_path) for block in parsed.blocks
    ] == [
        (ParsedBlockKind.HEADING, "文档", ("文档",)),
        (ParsedBlockKind.PARAGRAPH, "不是标题\n=-=", ("文档",)),
        (ParsedBlockKind.HEADING, "泵组", ("文档", "泵组")),
    ]


def test_markdown_parser_replaces_deeper_path_for_shallower_heading() -> None:
    parsed = MarkdownParser().parse(
        "# 船舶\n\n### 泵组\n\n检查。\n\n## 发电机\n\n复核。".encode()
    )

    assert [block.structural_path for block in parsed.blocks] == [
        ("船舶",),
        ("船舶", "泵组"),
        ("船舶", "泵组"),
        ("船舶", "发电机"),
        ("船舶", "发电机"),
    ]


def test_markdown_parser_keeps_raw_html_and_fenced_code_as_literal_paragraphs() -> None:
    parsed = MarkdownParser().parse(
        (
            "# 船舶\n\n<h2>原始 HTML</h2>\n\n```markdown\n## 不是标题\n"
            "| 项目 | 数量 |\n| --- | --- |\n| 泵 | 2 |\n```\n\n结束。"
        ).encode()
    )

    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.PARAGRAPH,
    ]
    assert parsed.blocks[1].text == "<h2>原始 HTML</h2>"
    assert parsed.blocks[2].text.startswith("```markdown\n## 不是标题")
    assert parsed.blocks[3].structural_path == ("船舶",)


def test_markdown_parser_keeps_multiline_raw_html_as_literal_content() -> None:
    parsed = MarkdownParser().parse(
        (
            "# 船舶\n\n<pre>\n# 必须保持文本\n| 项目 | 数量 |\n"
            "| --- | --- |\n| 泵 | 2 |\n</pre>\n\n## 实际结构\n\n"
            "| 项目 | 数量 |\n| --- | --- |\n| 阀 | 4 |"
        ).encode()
    )

    assert [(block.kind, block.structural_path) for block in parsed.blocks] == [
        (ParsedBlockKind.HEADING, ("船舶",)),
        (ParsedBlockKind.PARAGRAPH, ("船舶",)),
        (ParsedBlockKind.HEADING, ("船舶", "实际结构")),
        (ParsedBlockKind.TABLE, ("船舶", "实际结构")),
    ]
    assert parsed.blocks[1].text == (
        "<pre>\n# 必须保持文本\n| 项目 | 数量 |\n| --- | --- |\n| 泵 | 2 |\n</pre>"
    )
    assert parsed.blocks[3].table == (("项目", "数量"), ("阀", "4"))


@pytest.mark.parametrize(
    ("tag", "heading"),
    [
        ("<br>", "resumes"),
        ('<img alt="drawing" src="drawing.png">', "image resumes"),
    ],
)
def test_markdown_parser_does_not_open_multiline_state_for_void_html_tags(
    tag: str, heading: str
) -> None:
    parsed = MarkdownParser().parse(f"{tag}\n\n# {heading}".encode())

    assert [
        (block.kind, block.text, block.structural_path) for block in parsed.blocks
    ] == [
        (ParsedBlockKind.PARAGRAPH, tag, ()),
        (ParsedBlockKind.HEADING, heading, (heading,)),
    ]


def test_markdown_parser_keeps_inline_html_literal_and_heading() -> None:
    parsed = MarkdownParser().parse(b"<span>literal</span>\n\n# resumes")

    assert [
        (block.kind, block.text, block.structural_path) for block in parsed.blocks
    ] == [
        (ParsedBlockKind.PARAGRAPH, "<span>literal</span>", ()),
        (ParsedBlockKind.HEADING, "resumes", ("resumes",)),
    ]


def test_markdown_parser_normalizes_ragged_table_rows() -> None:
    parsed = MarkdownParser().parse(
        (
            "| 项目 | 数量 | 备注 |\n| :--- | ---: | :---: |\n"
            "| 泵 | 2 |\n| 阀 | 4 | 已验收 |"
        ).encode()
    )

    assert parsed.blocks[0].table == (
        ("项目", "数量", "备注"),
        ("泵", "2", ""),
        ("阀", "4", "已验收"),
    )


def test_markdown_parser_rejects_a_row_wider_than_the_column_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.ingestion.parser.MAX_TABLE_COLUMNS", 2)

    with pytest.raises(ParserError) as raised:
        MarkdownParser().parse(b"| item | qty |\n| --- | --- |\n| pump | 2 | extra |")

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


@pytest.mark.parametrize("parser_factory", _TEXT_PARSER_FACTORIES)
def test_text_parsers_accept_utf8_bom(
    parser_factory: Callable[[], Parser],
) -> None:
    parser = parser_factory()

    parsed = parser.parse("\ufeff泵组检查。".encode())

    assert parsed.blocks[0].text == "泵组检查。"


@pytest.mark.parametrize("parser_factory", _TEXT_PARSER_FACTORIES)
def test_text_parsers_reject_invalid_utf8_with_safe_typed_error(
    parser_factory: Callable[[], Parser],
) -> None:
    with pytest.raises(ParserError) as raised:
        parser_factory().parse(b"\xff")

    _assert_parser_error(raised, ParserErrorCode.UNSUPPORTED_ENCODING)


@pytest.mark.parametrize("parser_factory", _TEXT_PARSER_FACTORIES)
def test_text_parsers_reject_nul_with_safe_typed_error(
    parser_factory: Callable[[], Parser],
) -> None:
    with pytest.raises(ParserError) as raised:
        parser_factory().parse("泵\x00组".encode())

    _assert_parser_error(raised, ParserErrorCode.INVALID_DOCUMENT)


@pytest.mark.parametrize("parser_factory", _TEXT_PARSER_FACTORIES)
def test_text_parsers_reject_all_blank_input_with_safe_typed_error(
    parser_factory: Callable[[], Parser],
) -> None:
    with pytest.raises(ParserError) as raised:
        parser_factory().parse(b" \r\n\t\n")

    _assert_parser_error(raised, ParserErrorCode.EMPTY_DOCUMENT)


def test_txt_parser_accepts_exact_source_size_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.ingestion.parser.MAX_SOURCE_BYTES", 4)

    parsed = TxtParser().parse(b"pump")

    assert parsed.blocks[0].text == "pump"


def test_txt_parser_rejects_oversized_block_with_safe_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.ingestion.parser.MAX_BLOCK_CHARS", 3)

    with pytest.raises(ParserError) as raised:
        TxtParser().parse(b"pump")

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_txt_parser_stops_consuming_paragraphs_at_block_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paragraphs = _ExplodingSequence(
        ("first", "second"), "TXT consumed content after exceeding the block limit"
    )
    monkeypatch.setattr(
        "adapters.parsers.text._paragraphs",
        lambda _text: paragraphs,
        raising=False,
    )
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 1)

    with pytest.raises(ParserError) as raised:
        TxtParser().parse(b"synthetic")

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_markdown_parser_stops_parsing_lines_at_block_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import adapters.parsers.markdown as markdown_module

    original = markdown_module._atx_heading
    calls = 0

    def observed_heading(line: str) -> tuple[int, str] | None:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise AssertionError(
                "Markdown parsed content after exceeding the block limit"
            )
        return original(line)

    monkeypatch.setattr(markdown_module, "_atx_heading", observed_heading)
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 1)

    with pytest.raises(ParserError) as raised:
        MarkdownParser().parse(b"# first\n# second\n# third")

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_docx_parser_stops_consuming_body_items_at_block_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ParagraphStub:
        style = None

        def __init__(self, text: str) -> None:
            self.text = text

    class DocumentStub:
        def iter_inner_content(self) -> _ExplodingSequence[ParagraphStub]:
            return _ExplodingSequence(
                (ParagraphStub("first"), ParagraphStub("second")),
                "DOCX consumed content after exceeding the block limit",
            )

    monkeypatch.setattr("adapters.parsers.docx.Paragraph", ParagraphStub)
    monkeypatch.setattr("adapters.parsers.docx.Document", lambda *_a: DocumentStub())
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 1)

    with pytest.raises(ParserError) as raised:
        DocxParser().parse(synthetic_docx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_xlsx_parser_stops_consuming_worksheets_at_block_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WorkbookStub:
        def __init__(self) -> None:
            self.worksheets = _ExplodingSequence(
                (
                    _WorksheetStub((("first",),)),
                    _WorksheetStub((("second",),)),
                ),
                "XLSX consumed content after exceeding the block limit",
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr("openpyxl.load_workbook", lambda *_a, **_k: WorkbookStub())
    monkeypatch.setattr(parser_contract, "MAX_BLOCKS", 1)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(synthetic_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


@pytest.mark.parametrize(
    ("limit", "value"),
    [("MAX_BLOCKS", 1), ("MAX_TOTAL_TEXT_CHARS", 5)],
)
def test_pdf_parser_stops_consuming_pages_at_output_limit(
    limit: str,
    value: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _ExplodingSequence(
        (_PdfPageStub("one"), _PdfPageStub("two")),
        "PDF consumed content after exceeding the output limit",
    )
    monkeypatch.setattr(
        "adapters.parsers.pdf.PdfReader", lambda *_a, **_k: _PdfReaderStub(pages)
    )
    monkeypatch.setattr(parser_contract, limit, value)

    with pytest.raises(ParserError) as raised:
        PdfParser().parse(synthetic_pdf_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)


def test_xlsx_parser_stops_collecting_table_before_render_at_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WorksheetStub:
        title = "Stub"

        def reset_dimensions(self) -> None:
            pass

        def iter_rows(self, *, values_only: bool) -> _ExplodingSequence[tuple[str]]:
            assert values_only is True
            return _ExplodingSequence(
                (("oversized",),),
                "XLSX continued collecting cells after the table text limit",
            )

    class WorkbookStub:
        def __init__(self) -> None:
            self.worksheets = [WorksheetStub()]
            self.closed = False

        def close(self) -> None:
            self.closed = True

    workbook = WorkbookStub()
    monkeypatch.setattr("openpyxl.load_workbook", lambda *_a, **_k: workbook)
    monkeypatch.setattr(parser_contract, "MAX_BLOCK_CHARS", 3)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(synthetic_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)
    assert workbook.closed is True


def test_xlsx_parser_counts_table_separators_before_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells = _ExplodingSequence(
        ("x", "", "y"),
        "XLSX continued collecting cells after separators exceeded the limit",
    )

    class WorksheetStub:
        title = "Stub"

        def reset_dimensions(self) -> None:
            pass

        def iter_rows(
            self, *, values_only: bool
        ) -> tuple[_ExplodingSequence[str], ...]:
            assert values_only is True
            return (cells,)

    class WorkbookStub:
        worksheets = [WorksheetStub()]

        def close(self) -> None:
            pass

    monkeypatch.setattr("openpyxl.load_workbook", lambda *_a, **_k: WorkbookStub())
    monkeypatch.setattr(parser_contract, "MAX_BLOCK_CHARS", 3)

    with pytest.raises(ParserError) as raised:
        XlsxParser().parse(synthetic_xlsx_bytes())

    _assert_parser_error(raised, ParserErrorCode.RESOURCE_LIMIT)
