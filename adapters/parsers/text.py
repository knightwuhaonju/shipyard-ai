"""Deterministic UTF-8 plain-text parser."""

from __future__ import annotations

import re
from collections.abc import Iterator

from services.ingestion import (
    DocumentFormat,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    validate_source_bytes,
)

from ._common import BlockAccumulator


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
            blocks = BlockAccumulator(self.format)
            for paragraph in _paragraphs(normalized):
                blocks.append(ParsedBlockKind.PARAGRAPH, paragraph)
            return blocks.document()
        except ValueError as error:
            raise _contract_error(error) from None


def _paragraphs(text: str) -> Iterator[str]:
    start = 0
    for separator in re.finditer(r"\n\n+", text):
        yield text[start : separator.start()]
        start = separator.end()
    yield text[start:]


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
