"""Framework-independent contracts shared by document parser adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_BLOCKS = 10_000
MAX_BLOCK_CHARS = 1_000_000
MAX_TOTAL_TEXT_CHARS = 5_000_000
MAX_TABLE_ROWS = 10_000
MAX_TABLE_COLUMNS = 256
MAX_TABLE_CELLS = 100_000
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MAX_PDF_PAGES = 2_000
MAX_PDF_PAGE_STREAM_BYTES = 10 * 1024 * 1024


class DocumentFormat(StrEnum):
    """Explicit formats supported by the ingestion parser boundary."""

    TXT = "txt"
    MARKDOWN = "markdown"
    DOCX = "docx"
    XLSX = "xlsx"
    PDF = "pdf"


class ParsedBlockKind(StrEnum):
    """Semantic structures a parser can preserve without chunking."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    PAGE = "page"


class ParserErrorCode(StrEnum):
    """Safe, adapter-independent public parsing failure classifications."""

    INVALID_DOCUMENT = "invalid_document"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    ENCRYPTED_DOCUMENT = "encrypted_document"
    RESOURCE_LIMIT = "resource_limit"
    EMPTY_DOCUMENT = "empty_document"
    OCR_REQUIRED = "ocr_required"


_ERROR_MESSAGES: dict[ParserErrorCode, str] = {
    ParserErrorCode.INVALID_DOCUMENT: "document cannot be parsed",
    ParserErrorCode.UNSUPPORTED_ENCODING: "document text encoding is unsupported",
    ParserErrorCode.ENCRYPTED_DOCUMENT: "encrypted documents are unsupported",
    ParserErrorCode.RESOURCE_LIMIT: "document exceeds parser resource limits",
    ParserErrorCode.EMPTY_DOCUMENT: "document contains no parseable content",
    ParserErrorCode.OCR_REQUIRED: "PDF has no extractable text layer",
}


class ParserError(RuntimeError):
    """A safe public error raised by parser adapters."""

    def __init__(self, code: ParserErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


type TableCells = tuple[tuple[str, ...], ...]


class Parser(Protocol):
    """A bytes-only, side-effect-free document parser port."""

    @property
    def format(self) -> DocumentFormat: ...

    def parse(self, content: bytes) -> ParsedDocument: ...


def normalize_block_text(text: str) -> str:
    """Normalize line endings and surrounding block whitespace safely."""
    _require_text(text, "text")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def normalize_table_cell(cell: str) -> str:
    """Canonicalize a table cell without changing Unicode code points."""
    _require_text(cell, "table cell")
    normalized = cell.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[\t\n\f\v ]+", " ", normalized).strip()


def render_table(cells: TableCells) -> str:
    """Return deterministic tab/newline text for a rectangular table."""
    canonical = _canonical_table(cells)
    return "\n".join("\t".join(row) for row in canonical)


def validate_source_bytes(content: bytes) -> None:
    """Reject invalid source inputs before a format library sees their bytes."""
    if not isinstance(content, bytes):
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
    if not content:
        raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
    if len(content) > MAX_SOURCE_BYTES:
        raise ParserError(ParserErrorCode.RESOURCE_LIMIT)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedBlock:
    """One immutable parser output block in source order."""

    ordinal: int
    kind: ParsedBlockKind
    text: str
    structural_path: tuple[str, ...] = ()
    page: int | None = None
    sheet: str | None = None
    table: TableCells | None = None

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            raise ValueError("ordinal must be a non-negative integer")
        if self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(self.kind, ParsedBlockKind):
            raise ValueError("kind must be a ParsedBlockKind")
        _require_non_blank_text(self.text, "text")
        _validate_structural_path(self.structural_path)
        _validate_page(self.page)
        _validate_sheet(self.sheet)

        if self.kind is ParsedBlockKind.PAGE:
            if self.page is None:
                raise ValueError("PAGE blocks require page")
            if self.table is not None:
                raise ValueError("PAGE blocks cannot have table")
        elif self.kind is ParsedBlockKind.TABLE:
            if self.table is None:
                raise ValueError("TABLE blocks require table")
            if self.page is not None:
                raise ValueError("TABLE blocks cannot have page")
            canonical = _canonical_table(self.table)
            if self.table != canonical:
                raise ValueError("table must use canonical cells")
            if self.text != render_table(self.table):
                raise ValueError("TABLE blocks must have canonical text")
        elif self.table is not None:
            raise ValueError("table is only allowed for TABLE blocks")

        if len(self.text) > MAX_BLOCK_CHARS:
            raise ValueError("text exceeds maximum block length")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedDocument:
    """A non-empty ordered parser result for one explicit source format."""

    format: DocumentFormat
    blocks: tuple[ParsedBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.format, DocumentFormat):
            raise ValueError("format must be a DocumentFormat")
        if not isinstance(self.blocks, tuple):
            raise ValueError("blocks must be a tuple of ParsedBlock")
        if not self.blocks:
            raise ValueError("blocks must not be empty")
        if len(self.blocks) > MAX_BLOCKS:
            raise ValueError("blocks exceed maximum count")

        total_text_chars = 0
        for expected_ordinal, block in enumerate(self.blocks):
            if not isinstance(block, ParsedBlock):
                raise ValueError("blocks must be a tuple of ParsedBlock")
            if block.ordinal != expected_ordinal:
                raise ValueError("blocks must have contiguous ordinals")
            if block.sheet is not None and self.format is not DocumentFormat.XLSX:
                raise ValueError("sheet is only allowed for XLSX documents")
            total_text_chars += len(block.text)
        if total_text_chars > MAX_TOTAL_TEXT_CHARS:
            raise ValueError("blocks exceed maximum total text length")


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if "\x00" in value:
        raise ValueError(f"{field} must not contain NUL")


def _require_non_blank_text(value: str, field: str) -> None:
    _require_text(value, field)
    if not value.strip():
        raise ValueError(f"{field} must be non-blank")


def _validate_structural_path(path: tuple[str, ...]) -> None:
    if not isinstance(path, tuple):
        raise ValueError("structural_path must be a tuple of non-blank strings")
    for value in path:
        if not isinstance(value, str) or "\x00" in value or not value.strip():
            raise ValueError("structural_path must be non-blank")


def _validate_page(page: int | None) -> None:
    if page is None:
        return
    if isinstance(page, bool) or not isinstance(page, int) or page <= 0:
        raise ValueError("page must be a positive integer")


def _validate_sheet(sheet: str | None) -> None:
    if sheet is None:
        return
    _require_non_blank_text(sheet, "sheet")


def _canonical_table(cells: TableCells) -> TableCells:
    if not isinstance(cells, tuple) or not cells:
        raise ValueError("table must be a non-empty rectangular tuple of rows")
    if len(cells) > MAX_TABLE_ROWS:
        raise ValueError("table exceeds maximum row count")

    rows: list[tuple[str, ...]] = []
    column_count: int | None = None
    for row in cells:
        if not isinstance(row, tuple) or not row:
            raise ValueError("table must be a non-empty rectangular tuple of rows")
        if column_count is None:
            column_count = len(row)
            if column_count > MAX_TABLE_COLUMNS:
                raise ValueError("table exceeds maximum column count")
        elif len(row) != column_count:
            raise ValueError("table must be rectangular")
        canonical_row: list[str] = []
        for cell in row:
            canonical_row.append(normalize_table_cell(cell))
        rows.append(tuple(canonical_row))

    if column_count is None or len(rows) * column_count > MAX_TABLE_CELLS:
        raise ValueError("table exceeds maximum cell count")

    last_row = max(
        (index for index, row in enumerate(rows) if any(cell for cell in row)),
        default=-1,
    )
    if last_row < 0:
        raise ValueError("table must contain a non-empty cell")
    retained_rows = rows[: last_row + 1]
    last_column = max(
        (
            index
            for index in range(column_count)
            if any(row[index] for row in retained_rows)
        ),
        default=-1,
    )
    return tuple(row[: last_column + 1] for row in retained_rows)
