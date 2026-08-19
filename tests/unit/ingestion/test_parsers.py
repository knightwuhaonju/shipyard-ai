"""Tests for the immutable, parser-neutral ingestion contract."""

import socket
import struct
import warnings
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import services.ingestion.parser as parser_contract
from adapters.parsers._common import validate_ooxml_archive
from adapters.parsers.docx import DocxParser
from adapters.parsers.markdown import MarkdownParser
from adapters.parsers.text import TxtParser
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
    heading_hierarchy_docx_bytes,
    merged_table_docx_bytes,
    synthetic_docx_bytes,
    synthetic_markdown_bytes,
    synthetic_txt_bytes,
)

_PARSER_ERROR_MESSAGES = {
    ParserErrorCode.INVALID_DOCUMENT: "document cannot be parsed",
    ParserErrorCode.UNSUPPORTED_ENCODING: "document text encoding is unsupported",
    ParserErrorCode.RESOURCE_LIMIT: "document exceeds parser resource limits",
    ParserErrorCode.EMPTY_DOCUMENT: "document contains no parseable content",
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


def _assert_parser_error(
    raised: pytest.ExceptionInfo[ParserError], code: ParserErrorCode
) -> None:
    assert raised.value.code is code
    assert str(raised.value) == _PARSER_ERROR_MESSAGES[code]


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
