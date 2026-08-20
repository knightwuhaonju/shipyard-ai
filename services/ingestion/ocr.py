"""Optional, engine-independent PDF OCR service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

import services.ingestion.parser as parser_contract
from services.ingestion.parser import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    Parser,
    ParserError,
    ParserErrorCode,
    normalize_block_text,
    validate_source_bytes,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrPage:
    page: int
    text: str

    def __post_init__(self) -> None:
        if type(self.page) is not int or self.page <= 0:
            raise ValueError("page must be a positive integer")
        if type(self.text) is not str or "\x00" in self.text:
            raise ValueError("text must be a string without NUL")


class OcrPort(Protocol):
    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]: ...


class OcrFallbackParser:
    def __init__(self, primary: Parser, *, ocr: OcrPort | None = None) -> None:
        if primary.format is not DocumentFormat.PDF:
            raise ValueError("primary parser must use PDF format")
        self._primary = primary
        self._ocr = ocr

    @property
    def format(self) -> DocumentFormat:
        return DocumentFormat.PDF

    def parse(self, content: bytes) -> ParsedDocument:
        validate_source_bytes(content)
        try:
            return self._primary.parse(content)
        except ParserError as error:
            if error.code is not ParserErrorCode.OCR_REQUIRED or self._ocr is None:
                raise

        pages = self._ocr.recognize_pdf(content)
        return _ocr_document(pages)


def _ocr_document(result: object) -> ParsedDocument:
    if type(result) is not tuple:
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
    pages = cast(tuple[object, ...], result)
    blocks: list[ParsedBlock] = []
    previous_page = 0
    total_chars = 0

    for item in pages:
        if type(item) is not OcrPage:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        if type(item.page) is not int or item.page <= previous_page:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        if item.page > parser_contract.MAX_PDF_PAGES:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        previous_page = item.page
        try:
            text = normalize_block_text(item.text)
        except ValueError:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None
        if not text:
            continue
        if (
            len(blocks) >= parser_contract.MAX_BLOCKS
            or len(text) > parser_contract.MAX_BLOCK_CHARS
            or total_chars + len(text) > parser_contract.MAX_TOTAL_TEXT_CHARS
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
        blocks.append(
            ParsedBlock(
                ordinal=len(blocks),
                kind=ParsedBlockKind.PAGE,
                text=text,
                page=item.page,
            )
        )
        total_chars += len(text)

    if not blocks:
        raise ParserError(ParserErrorCode.EMPTY_DOCUMENT)
    return ParsedDocument(format=DocumentFormat.PDF, blocks=tuple(blocks))
