"""Tests for the immutable, parser-neutral ingestion contract."""

from dataclasses import FrozenInstanceError

import pytest

from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    normalize_table_cell,
    render_table,
    validate_source_bytes,
)


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
