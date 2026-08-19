"""Security preflight shared by ZIP-based OOXML parser adapters."""

from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, LargeZipFile, ZipFile

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
)

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:/")
_ZIP_ENCRYPTED_FLAG = 0x1
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


class BlockAccumulator:
    """Build parser output while enforcing cross-format budgets before append."""

    def __init__(self, format_: DocumentFormat) -> None:
        self._format = format_
        self._blocks: list[ParsedBlock] = []
        self._total_text_chars = 0

    @property
    def is_empty(self) -> bool:
        """Return whether no parseable block has been appended."""
        return not self._blocks

    def append(
        self,
        kind: ParsedBlockKind,
        text: str,
        *,
        structural_path: tuple[str, ...] = (),
        page: int | None = None,
        sheet: str | None = None,
        table: TableCells | None = None,
    ) -> None:
        """Validate budgets and append one immutable block."""
        self._check_block_capacity()
        self._check_text_budget(len(text))
        try:
            block = ParsedBlock(
                ordinal=len(self._blocks),
                kind=kind,
                text=text,
                structural_path=structural_path,
                page=page,
                sheet=sheet,
                table=table,
            )
        except ValueError as error:
            raise _contract_error(error) from None
        self._blocks.append(block)
        self._total_text_chars += len(text)

    def table(self) -> TableAccumulator:
        """Return a bounded collector for one prospective table block."""
        return TableAccumulator(self)

    def document(self) -> ParsedDocument:
        """Return the validated immutable document assembled so far."""
        try:
            return ParsedDocument(format=self._format, blocks=tuple(self._blocks))
        except ValueError as error:
            raise _contract_error(error) from None

    def _check_block_capacity(self) -> None:
        if len(self._blocks) >= parser_contract.MAX_BLOCKS:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

    def _check_text_budget(self, additional_chars: int) -> None:
        if (
            additional_chars > parser_contract.MAX_BLOCK_CHARS
            or self._total_text_chars + additional_chars
            > parser_contract.MAX_TOTAL_TEXT_CHARS
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)


class TableAccumulator:
    """Collect normalized cells under table and output-character limits."""

    def __init__(self, blocks: BlockAccumulator) -> None:
        self._blocks = blocks
        self._rows: list[list[str]] = []
        self._maximum_columns = 0
        self._scanned_cells = 0
        self._normalized_chars = 0
        self._last_nonempty_row = -1
        self._last_nonempty_column = -1
        self._block_capacity_checked = False

    def append_row(self, cells: Iterable[str]) -> None:
        """Normalize and retain one row, stopping as soon as a limit is crossed."""
        if len(self._rows) >= parser_contract.MAX_TABLE_ROWS:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

        row: list[str] = []
        for cell in cells:
            if (
                len(row) >= parser_contract.MAX_TABLE_COLUMNS
                or self._scanned_cells >= parser_contract.MAX_TABLE_CELLS
            ):
                raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
            try:
                normalized = normalize_table_cell(cell)
            except ValueError:
                raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None
            prospective_chars = self._normalized_chars + len(normalized)
            prospective_last_row = self._last_nonempty_row
            prospective_last_column = self._last_nonempty_column
            if normalized:
                prospective_last_row = len(self._rows)
                prospective_last_column = max(prospective_last_column, len(row))
            rendered_chars = 0
            if prospective_last_row >= 0:
                rendered_chars = prospective_chars + (
                    (prospective_last_row + 1) * (prospective_last_column + 1) - 1
                )
            self._blocks._check_text_budget(rendered_chars)
            if normalized and not self._block_capacity_checked:
                self._blocks._check_block_capacity()
                self._block_capacity_checked = True
            row.append(normalized)
            self._scanned_cells += 1
            self._normalized_chars = prospective_chars
            self._last_nonempty_row = prospective_last_row
            self._last_nonempty_column = prospective_last_column

        maximum_columns = max(self._maximum_columns, len(row))
        if (
            maximum_columns > parser_contract.MAX_TABLE_COLUMNS
            or (len(self._rows) + 1) * maximum_columns
            > parser_contract.MAX_TABLE_CELLS
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        self._maximum_columns = maximum_columns
        self._rows.append(row)

    def finish(self) -> tuple[TableCells, str] | None:
        """Trim empty trailing edges and render the canonical table once."""
        if self._maximum_columns == 0 or not any(
            cell for row in self._rows for cell in row
        ):
            return None

        rectangular = [
            row + [""] * (self._maximum_columns - len(row)) for row in self._rows
        ]
        last_row = max(
            index for index, row in enumerate(rectangular) if any(cell for cell in row)
        )
        retained_rows = rectangular[: last_row + 1]
        last_column = max(
            index
            for index in range(self._maximum_columns)
            if any(row[index] for row in retained_rows)
        )
        canonical = tuple(
            tuple(row[: last_column + 1]) for row in retained_rows
        )
        text = "\n".join("\t".join(row) for row in canonical)
        self._blocks._check_text_budget(len(text))
        return canonical, text


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)


def validate_ooxml_archive(content: bytes) -> None:
    """Validate OOXML ZIP member metadata without extracting any content."""
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
    except (BadZipFile, LargeZipFile):
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None

    if len(members) > parser_contract.MAX_ARCHIVE_ENTRIES:
        raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

    normalized_names: set[str] = set()
    uncompressed_total = 0
    for member in members:
        normalized_name = member.filename.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        if (
            not normalized_name
            or member.flag_bits & _ZIP_ENCRYPTED_FLAG
            or member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or normalized_name in normalized_names
            or path.is_absolute()
            or _WINDOWS_ABSOLUTE_PATH.match(normalized_name) is not None
            or ".." in path.parts
        ):
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        normalized_names.add(normalized_name)

        uncompressed_total += member.file_size
        if uncompressed_total > parser_contract.MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

        if normalized_name.endswith("/") or member.file_size == 0:
            continue
        if (
            member.compress_size == 0
            or member.file_size
            > parser_contract.MAX_ARCHIVE_COMPRESSION_RATIO * member.compress_size
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
