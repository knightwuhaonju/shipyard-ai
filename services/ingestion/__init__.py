"""Document ingestion application services."""

from services.ingestion.chunker import DEFAULT_MAX_CHARS, StructuralChunker
from services.ingestion.document_store import (
    DocumentChunkConflictError,
    DocumentConflictError,
    DocumentNotFoundError,
    DocumentRepository,
    DocumentRepositoryError,
    DocumentStore,
    DocumentStoreError,
    DocumentVersionConflictError,
    DocumentVersionNotFoundError,
)
from services.ingestion.ocr import OcrPage, OcrPort
from services.ingestion.parser import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    Parser,
    ParserError,
    ParserErrorCode,
    TableCells,
    normalize_block_text,
    normalize_table_cell,
    render_table,
    validate_source_bytes,
)

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DocumentChunkConflictError",
    "DocumentConflictError",
    "DocumentNotFoundError",
    "DocumentRepository",
    "DocumentRepositoryError",
    "DocumentStore",
    "DocumentStoreError",
    "DocumentVersionConflictError",
    "DocumentVersionNotFoundError",
    "DocumentFormat",
    "ParsedBlock",
    "ParsedBlockKind",
    "ParsedDocument",
    "Parser",
    "ParserError",
    "ParserErrorCode",
    "StructuralChunker",
    "TableCells",
    "normalize_block_text",
    "normalize_table_cell",
    "render_table",
    "validate_source_bytes",
    "OcrPage",
    "OcrPort",
]
