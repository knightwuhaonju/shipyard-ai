"""Optional, engine-independent PDF OCR service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


def _ocr_document(pages: tuple[OcrPage, ...]) -> ParsedDocument:
    blocks: list[ParsedBlock] = []
    for page in pages:
        text = normalize_block_text(page.text)
        if not text:
            continue
        blocks.append(
            ParsedBlock(
                ordinal=len(blocks),
                kind=ParsedBlockKind.PAGE,
                text=text,
                page=page.page,
            )
        )
    return ParsedDocument(format=DocumentFormat.PDF, blocks=tuple(blocks))
