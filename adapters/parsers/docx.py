"""Safe, source-ordered DOCX parser for ingestion."""

from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from zipfile import BadZipFile, LargeZipFile

from docx import Document
from docx.opc.exceptions import OpcError
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError  # type: ignore[import-untyped]

from adapters.parsers._common import validate_ooxml_archive
from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    TableCells,
    normalize_block_text,
    normalize_table_cell,
    render_table,
    validate_source_bytes,
)

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
            if not blocks:
                raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
            return ParsedDocument(format=self.format, blocks=tuple(blocks))
        except ParserError:
            raise
        except ValueError as error:
            raise _contract_error(error) from error
        except (
            BadZipFile,
            KeyError,
            LargeZipFile,
            OpcError,
            XMLSyntaxError,
        ) as error:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from error


def _document_blocks(content: Iterable[Paragraph | Table]) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
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
                ParsedBlock(
                    ordinal=len(blocks),
                    kind=kind,
                    text=text,
                    structural_path=_structural_path(title, headings),
                )
            )
            continue

        if isinstance(item, Table):
            table = _table_cells(item)
            if table is None:
                continue
            cells, text = table
            blocks.append(
                ParsedBlock(
                    ordinal=len(blocks),
                    kind=ParsedBlockKind.TABLE,
                    text=text,
                    structural_path=_structural_path(title, headings),
                    table=cells,
                )
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


def _table_cells(table: Table) -> tuple[TableCells, str] | None:
    rows: list[list[str]] = []
    width = 0
    for row in table.rows:
        values = [""] * row.grid_cols_before
        seen_cells: list[object] = []
        for cell in row.cells:
            if any(cell is seen for seen in seen_cells):
                values.append("")
            else:
                seen_cells.append(cell)
                values.append(normalize_table_cell(cell.text))
        values.extend([""] * row.grid_cols_after)
        width = max(width, len(values))
        rows.append(values)

    if width == 0 or not any(cell for row in rows for cell in row):
        return None

    rectangular = tuple(tuple(row + [""] * (width - len(row))) for row in rows)
    text = render_table(rectangular)
    canonical = tuple(tuple(line.split("\t")) for line in text.split("\n"))
    return canonical, text


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
