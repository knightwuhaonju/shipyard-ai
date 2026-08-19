"""Tests for the immutable, parser-neutral ingestion contract."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

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


def test_markdown_parser_recognizes_setext_headings() -> None:
    parsed = MarkdownParser().parse(
        "合成规范\n====\n\n泵组\n----\n\n检查轴封。".encode()
    )

    assert [(block.kind, block.structural_path) for block in parsed.blocks] == [
        (ParsedBlockKind.HEADING, ("合成规范",)),
        (ParsedBlockKind.HEADING, ("合成规范", "泵组")),
        (ParsedBlockKind.PARAGRAPH, ("合成规范", "泵组")),
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
