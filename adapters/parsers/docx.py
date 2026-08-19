"""Safe, source-ordered DOCX parser for ingestion."""

from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, LargeZipFile

from docx import Document
from docx.opc.exceptions import OpcError
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError  # type: ignore[import-untyped]

from services.ingestion import (
    DocumentFormat,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    TableCells,
    normalize_block_text,
    validate_source_bytes,
)

from ._common import BlockAccumulator, TableAccumulator, validate_ooxml_archive

_HEADING_STYLE = re.compile(r"^Heading ([1-9])$")
_RESOURCE_LIMIT_ERRORS = frozenset(
    {
        "text exceeds maximum block length",
        "blocks exceed maximum count",
        "blocks exceed maximum total text length",
        "table exceeds maximum row count",
        "table exceeds maximum column count",
        "table exceeds maximum cell count",
    }
)


class DocxParser:
    """Parse DOCX bytes without following relationships or extracting files."""

    @property
    def format(self) -> DocumentFormat:
        """Return the explicit format served by this parser."""
        return DocumentFormat.DOCX

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse top-level paragraphs and tables in document source order."""
        validate_source_bytes(content)
        validate_ooxml_archive(content)
        try:
            document = Document(BytesIO(content))
            blocks = _document_blocks(document.iter_inner_content())
            if blocks.is_empty:
                raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
            return blocks.document()
        except ParserError:
            raise
        except ValueError as error:
            raise _contract_error(error) from None
        except (
            BadZipFile,
            KeyError,
            LargeZipFile,
            OpcError,
            XMLSyntaxError,
        ):
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None


def _document_blocks(content: Iterable[Paragraph | Table]) -> BlockAccumulator:
    blocks = BlockAccumulator(DocumentFormat.DOCX)
    title: str | None = None
    headings: list[tuple[int, str]] = []

    for item in content:
        if isinstance(item, Paragraph):
            text = normalize_block_text(item.text)
            if not text:
                continue
            style_name = item.style.name if item.style is not None else ""
            if style_name == "Title":
                title = text
                headings.clear()
                kind = ParsedBlockKind.TITLE
            else:
                heading = _HEADING_STYLE.fullmatch(style_name)
                if heading is not None:
                    _replace_heading(headings, int(heading.group(1)), text)
                    kind = ParsedBlockKind.HEADING
                else:
                    kind = ParsedBlockKind.PARAGRAPH
            blocks.append(
                kind,
                text,
                structural_path=_structural_path(title, headings),
            )
            continue

        if isinstance(item, Table):
            table = _table_cells(item, blocks.table())
            if table is None:
                continue
            cells, text = table
            blocks.append(
                ParsedBlockKind.TABLE,
                text,
                structural_path=_structural_path(title, headings),
                table=cells,
            )

    return blocks


def _replace_heading(headings: list[tuple[int, str]], level: int, text: str) -> None:
    while headings and headings[-1][0] >= level:
        headings.pop()
    headings.append((level, text))


def _structural_path(
    title: str | None, headings: list[tuple[int, str]]
) -> tuple[str, ...]:
    root = (title,) if title is not None else ()
    return root + tuple(text for _, text in headings)


def _table_cells(
    table: Table, cells: TableAccumulator
) -> tuple[TableCells, str] | None:
    for row in table.rows:
        cells.append_row(_docx_row_cells(row))
    return cells.finish()


def _docx_row_cells(row: Any) -> Iterable[str]:
    for _ in range(row.grid_cols_before):
        yield ""
    seen_cells: list[object] = []
    for cell in row.cells:
        if any(cell is seen for seen in seen_cells):
            yield ""
        else:
            seen_cells.append(cell)
            yield cell.text
    for _ in range(row.grid_cols_after):
        yield ""


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
