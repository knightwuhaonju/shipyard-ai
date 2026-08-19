"""Deterministic UTF-8 plain-text parser."""

from __future__ import annotations

import re

from services.ingestion import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    validate_source_bytes,
)


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
            blocks = tuple(
                ParsedBlock(
                    ordinal=ordinal,
                    kind=ParsedBlockKind.PARAGRAPH,
                    text=paragraph,
                )
                for ordinal, paragraph in enumerate(re.split(r"\n\n+", normalized))
            )
            return ParsedDocument(format=self.format, blocks=blocks)
        except ValueError as error:
            raise _contract_error(error) from error


def _decode_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ParserError(ParserErrorCode.UNSUPPORTED_ENCODING) from error
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
