"""Safe, read-only XLSX worksheet parser for ingestion."""

from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, LargeZipFile

import openpyxl  # type: ignore[import-untyped]
from lxml.etree import XMLSyntaxError  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)

import services.ingestion.parser as parser_contract
from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    TableCells,
    normalize_table_cell,
    render_table,
    validate_source_bytes,
)

from ._common import validate_ooxml_archive

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


class XlsxParser:
    """Parse workbook bytes into one canonical table per non-empty sheet."""

    @property
    def format(self) -> DocumentFormat:
        """Return the explicit format served by this parser."""
        return DocumentFormat.XLSX

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse values without executing formulas, links, macros, or files."""
        validate_source_bytes(content)
        validate_ooxml_archive(content)

        workbook: Any = None
        try:
            workbook = openpyxl.load_workbook(
                BytesIO(content),
                read_only=True,
                data_only=False,
                keep_links=False,
                keep_vba=False,
            )
            blocks = _workbook_blocks(workbook)
            if not blocks:
                raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
            return ParsedDocument(format=self.format, blocks=tuple(blocks))
        except ParserError:
            raise
        except ValueError as error:
            raise _contract_error(error) from error
        except (
            BadZipFile,
            InvalidFileException,
            KeyError,
            LargeZipFile,
            XMLSyntaxError,
        ) as error:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from error
        finally:
            if workbook is not None:
                workbook.close()


def _workbook_blocks(workbook: Any) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for worksheet in workbook.worksheets:
        table = _worksheet_table(worksheet)
        if table is None:
            continue
        cells, text = table
        blocks.append(
            ParsedBlock(
                ordinal=len(blocks),
                kind=ParsedBlockKind.TABLE,
                text=text,
                structural_path=(worksheet.title,),
                sheet=worksheet.title,
                table=cells,
            )
        )
    return blocks


def _worksheet_table(worksheet: Any) -> tuple[TableCells, str] | None:
    worksheet.reset_dimensions()
    rows: list[list[str]] = []
    row_count = 0
    maximum_columns = 0
    scanned_cells = 0

    for values in worksheet.iter_rows(values_only=True):
        row_count += 1
        column_count = len(values)
        maximum_columns = max(maximum_columns, column_count)
        scanned_cells += column_count
        if (
            row_count > parser_contract.MAX_TABLE_ROWS
            or maximum_columns > parser_contract.MAX_TABLE_COLUMNS
            or scanned_cells > parser_contract.MAX_TABLE_CELLS
            or row_count * maximum_columns > parser_contract.MAX_TABLE_CELLS
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        rows.append([_cell_text(value) for value in values])

    if maximum_columns == 0 or not any(cell for row in rows for cell in row):
        return None

    rectangular = tuple(
        tuple(row + [""] * (maximum_columns - len(row))) for row in rows
    )
    text = render_table(rectangular)
    canonical = tuple(tuple(line.split("\t")) for line in text.split("\n"))
    return canonical, text


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, str):
        return normalize_table_cell(value)
    if isinstance(value, (int, float)):
        return normalize_table_cell(str(value))
    raise ValueError("unsupported XLSX cell value")


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
