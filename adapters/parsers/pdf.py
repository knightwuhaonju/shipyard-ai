"""Bounded text-layer PDF parser for ingestion."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, LimitReachedError, PdfReadError

import services.ingestion.parser as parser_contract
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

_RESOURCE_LIMIT_ERRORS = frozenset(
    {
        "text exceeds maximum block length",
        "blocks exceed maximum count",
        "blocks exceed maximum total text length",
    }
)


class PdfParser:
    """Parse only bounded, extractable PDF text without OCR or rendering."""

    @property
    def format(self) -> DocumentFormat:
        """Return the explicit format served by this parser."""
        return DocumentFormat.PDF

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse text-layer pages from in-memory PDF bytes."""
        validate_source_bytes(content)
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ParserError(ParserErrorCode.ENCRYPTED_DOCUMENT)
            if len(reader.pages) > parser_contract.MAX_PDF_PAGES:
                raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

            blocks = BlockAccumulator(self.format)
            for page_number, page in enumerate(reader.pages, start=1):
                contents = page.get_contents()
                if contents is not None:
                    decoded = contents.get_data()
                    if len(decoded) > parser_contract.MAX_PDF_PAGE_STREAM_BYTES:
                        raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
                extracted_text = page.extract_text()
                text = _normalized_extracted_text(extracted_text)
                if not text:
                    continue
                blocks.append(ParsedBlockKind.PAGE, text, page=page_number)

            if blocks.is_empty:
                raise ParserError(ParserErrorCode.OCR_REQUIRED)
            return blocks.document()
        except ParserError:
            raise
        except FileNotDecryptedError:
            raise ParserError(ParserErrorCode.ENCRYPTED_DOCUMENT) from None
        except LimitReachedError:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT) from None
        except PdfReadError:
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from None


def _normalized_extracted_text(text: str) -> str:
    try:
        return normalize_block_text(text)
    except ValueError as error:
        raise _contract_error(error) from None


def _contract_error(error: ValueError) -> ParserError:
    if str(error) in _RESOURCE_LIMIT_ERRORS:
        return ParserError(ParserErrorCode.RESOURCE_LIMIT)
    return ParserError(ParserErrorCode.INVALID_DOCUMENT)
