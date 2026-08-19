"""Deterministic, non-rendering Markdown parser for ingestion."""

from __future__ import annotations

import re

import services.ingestion.parser as parser_contract
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

_ATX_HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
_SETEXT_HEADING = re.compile(r"^[ \t]*(?:=+|-+)[ \t]*$")
_TABLE_DELIMITER_CELL = re.compile(r"^:?-{3,}:?$")
_FENCE_START = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_HTML_OPENING_TAG = re.compile(
    r"^[ \t]*<([A-Za-z][A-Za-z0-9:-]*)\b[^>]*>", re.IGNORECASE
)


class MarkdownParser:
    """Parse a deliberately small Markdown subset without rendering content."""

    @property
    def format(self) -> DocumentFormat:
        """Return the explicit format served by this parser."""
        return DocumentFormat.MARKDOWN

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse Markdown bytes into headings, paragraphs, and pipe tables."""
        validate_source_bytes(content)
        text = _decode_text(content)
        normalized = normalize_block_text(text)
        if not normalized:
            raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)

        try:
            return self._parse_normalized(normalized)
        except ValueError as error:
            raise _contract_error(error) from error

    def _parse_normalized(self, text: str) -> ParsedDocument:
        lines = text.split("\n")
        blocks: list[ParsedBlock] = []
        paragraph_lines: list[str] = []
        headings: list[str] = []
        fence: str | None = None
        raw_html_tag: str | None = None
        index = 0

        def append_block(
            kind: ParsedBlockKind,
            block_text: str,
            *,
            table: TableCells | None = None,
        ) -> None:
            blocks.append(
                ParsedBlock(
                    ordinal=len(blocks),
                    kind=kind,
                    text=block_text,
                    structural_path=tuple(headings),
                    table=table,
                )
            )

        def flush_paragraph() -> None:
            if paragraph_lines:
                append_block(ParsedBlockKind.PARAGRAPH, "\n".join(paragraph_lines))
                paragraph_lines.clear()

        while index < len(lines):
            line = lines[index]
            if fence is not None:
                paragraph_lines.append(line)
                if _is_closing_fence(line, fence):
                    fence = None
                index += 1
                continue

            if raw_html_tag is not None:
                paragraph_lines.append(line)
                if _contains_html_close(line, raw_html_tag):
                    raw_html_tag = None
                index += 1
                continue

            opening_fence = _opening_fence(line)
            if opening_fence is not None:
                paragraph_lines.append(line)
                fence = opening_fence
                index += 1
                continue

            opening_html = _opening_html_tag(line)
            if opening_html is not None:
                paragraph_lines.append(line)
                raw_html_tag = opening_html
                index += 1
                continue

            if not line.strip():
                flush_paragraph()
                index += 1
                continue

            atx_heading = _atx_heading(line)
            if atx_heading is not None:
                level, heading = atx_heading
                flush_paragraph()
                _replace_heading(headings, level, heading)
                append_block(ParsedBlockKind.HEADING, heading)
                index += 1
                continue

            if not paragraph_lines and index + 1 < len(lines):
                setext_level = _setext_level(lines[index + 1])
                if setext_level is not None:
                    heading = normalize_block_text(line)
                    if heading:
                        _replace_heading(headings, setext_level, heading)
                        append_block(ParsedBlockKind.HEADING, heading)
                        index += 2
                        continue

            if index + 1 < len(lines) and _is_table_header(line, lines[index + 1]):
                flush_paragraph()
                table, index = _consume_table(lines, index)
                append_block(ParsedBlockKind.TABLE, render_table(table), table=table)
                continue

            paragraph_lines.append(line)
            index += 1

        flush_paragraph()
        return ParsedDocument(format=self.format, blocks=tuple(blocks))


def _decode_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ParserError(ParserErrorCode.UNSUPPORTED_ENCODING) from error
    if "\x00" in text:
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
    return text


def _atx_heading(line: str) -> tuple[int, str] | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    heading = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2) or "")
    normalized = normalize_block_text(heading)
    if not normalized:
        return None
    return len(match.group(1)), normalized


def _setext_level(line: str) -> int | None:
    if _SETEXT_HEADING.match(line) is None:
        return None
    return 1 if line.strip()[0] == "=" else 2


def _replace_heading(headings: list[str], level: int, heading: str) -> None:
    del headings[level - 1 :]
    headings.append(heading)


def _opening_fence(line: str) -> str | None:
    match = _FENCE_START.match(line)
    return match.group(1) if match is not None else None


def _is_closing_fence(line: str, opening: str) -> bool:
    marker = re.compile(rf"^[ \t]*{re.escape(opening[0])}{{{len(opening)},}}[ \t]*$")
    return marker.match(line) is not None


def _opening_html_tag(line: str) -> str | None:
    match = _HTML_OPENING_TAG.match(line)
    if match is None or match.group(0).rstrip().endswith("/>"):
        return None
    tag = match.group(1)
    if _contains_html_close(line, tag):
        return None
    return tag


def _contains_html_close(line: str, tag: str) -> bool:
    pattern = rf"</[ \t]*{re.escape(tag)}[ \t]*>"
    return re.search(pattern, line, re.IGNORECASE) is not None


def _is_table_header(header: str, delimiter: str) -> bool:
    header_cells = _pipe_cells(header)
    delimiter_cells = _pipe_cells(delimiter)
    return (
        header_cells is not None
        and delimiter_cells is not None
        and len(header_cells) == len(delimiter_cells)
        and bool(header_cells)
        and all(_TABLE_DELIMITER_CELL.fullmatch(cell) for cell in delimiter_cells)
    )


def _consume_table(lines: list[str], index: int) -> tuple[TableCells, int]:
    header = _pipe_cells(lines[index])
    if header is None:
        raise ValueError("invalid Markdown table header")
    _validate_column_count(header)
    rows: list[tuple[str, ...]] = [tuple(header)]
    index += 2
    while index < len(lines):
        row = _pipe_cells(lines[index])
        if row is None:
            break
        _validate_column_count(row)
        if len(row) > len(header):
            raise ValueError("Markdown table row exceeds header width")
        rows.append(tuple(row + [""] * (len(header) - len(row))))
        index += 1
    return tuple(rows), index


def _pipe_cells(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    stripped = line.strip()
    cells = stripped.split("|")
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|"):
        cells = cells[:-1]
    return [normalize_table_cell(cell) for cell in cells]


def _validate_column_count(cells: list[str]) -> None:
    if len(cells) > parser_contract.MAX_TABLE_COLUMNS:
        raise ParserError(ParserErrorCode.RESOURCE_LIMIT)


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in {
        "text exceeds maximum block length",
        "blocks exceed maximum count",
        "blocks exceed maximum total text length",
        "table exceeds maximum row count",
        "table exceeds maximum column count",
        "table exceeds maximum cell count",
    }:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
