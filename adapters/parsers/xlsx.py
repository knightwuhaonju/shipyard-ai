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

from services.ingestion import (
    DocumentFormat,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    TableCells,
    validate_source_bytes,
)

from ._common import BlockAccumulator, TableAccumulator, validate_ooxml_archive

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
            if blocks.is_empty:
                raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
            return blocks.document()
        except ParserError:
            raise
        except ValueError as error:
            raise _contract_error(error) from None
        except (
            BadZipFile,
            InvalidFileException,
            KeyError,
            LargeZipFile,
            XMLSyntaxError,
        ):
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None
        finally:
            if workbook is not None:
                workbook.close()


def _workbook_blocks(workbook: Any) -> BlockAccumulator:
    blocks = BlockAccumulator(DocumentFormat.XLSX)
    for worksheet in workbook.worksheets:
        table = _worksheet_table(worksheet, blocks.table())
        if table is None:
            continue
        cells, text = table
        blocks.append(
            ParsedBlockKind.TABLE,
            text,
            structural_path=(worksheet.title,),
            sheet=worksheet.title,
            table=cells,
        )
    return blocks


def _worksheet_table(
    worksheet: Any, table: TableAccumulator
) -> tuple[TableCells, str] | None:
    worksheet.reset_dimensions()
    for values in worksheet.iter_rows(values_only=True):
        table.append_row(_cell_text(value) for value in values)
    return table.finish()


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    raise ValueError("unsupported XLSX cell value")


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
