"""Deterministic UTF-8 plain-text parser."""

from __future__ import annotations

from services.ingestion import (
    DocumentFormat,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    validate_source_bytes,
)

from ._common import BlockAccumulator, LineCursor


class TxtParser:
    """Parse UTF-8 text bytes into paragraph blocks."""

    @property
    def format(self) -> DocumentFormat:
        """Return the explicit format served by this parser."""
        return DocumentFormat.TXT

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse UTF-8 text without accessing files or executing content."""
        validate_source_bytes(content)
        text = _decode_text(content)
        normalized = normalize_block_text(text)
        if not normalized:
            raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)

        try:
            return self._parse_lines(LineCursor(normalized))
        except ValueError as error:
            raise _contract_error(error) from None

    def _parse_lines(self, lines: LineCursor) -> ParsedDocument:
        """Parse a real lazy line cursor into bounded paragraph blocks."""
        blocks = BlockAccumulator(self.format)
        paragraph = blocks.text()
        while (line := lines.pop()) is not None:
            if line:
                paragraph.append_line(line)
                continue
            paragraph.finish(ParsedBlockKind.PARAGRAPH)
        paragraph.finish(ParsedBlockKind.PARAGRAPH)
        if blocks.is_empty:
            raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
        return blocks.document()


def _decode_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParserError(ParserErrorCode.UNSUPPORTED_ENCODING) from None
    if "\x00" in text:
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
    return text


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in {
        "text exceeds maximum block length",
        "blocks exceed maximum count",
        "blocks exceed maximum total text length",
    }:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
