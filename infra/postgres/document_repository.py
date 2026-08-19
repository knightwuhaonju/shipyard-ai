"""PostgreSQL adapter for immutable document metadata."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres.document_models import (
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from packages.common import SecurityLevel
from packages.domain import (
    Document,
    DocumentChunk,
    DocumentValidationError,
    DocumentVersion,
)
from services.ingestion.document_store import DocumentRepositoryError

_CONSTRAINT_ERROR = "document record violates persistence constraints"
_INVALID_RECORD_ERROR = "stored document record is invalid"


def _to_document_model(document: Document) -> DocumentModel:
    return DocumentModel(
        document_id=document.document_id,
        source_system=document.source_system,
        source_id=document.source_id,
        title=document.title,
    )


def _to_version_model(version: DocumentVersion) -> DocumentVersionModel:
    return DocumentVersionModel(
        version_id=version.version_id,
        document_id=version.document_id,
        checksum=version.checksum,
        source_uri=version.source_uri,
        source_updated_at=version.source_updated_at,
        security_level=version.security_level.value,
        ship_id=version.ship_id,
        project_id=version.project_id,
        department=version.department,
    )


def _to_chunk_model(chunk: DocumentChunk) -> DocumentChunkModel:
    return DocumentChunkModel(
        chunk_id=chunk.chunk_id,
        version_id=chunk.version_id,
        structural_path=list(chunk.structural_path),
        ordinal=chunk.ordinal,
        normalized_text=chunk.normalized_text,
        page=chunk.page,
        section=chunk.section,
    )


def _to_document(model: DocumentModel) -> Document:
    try:
        return Document(
            document_id=model.document_id,
            source_system=model.source_system,
            source_id=model.source_id,
            title=model.title,
        )
    except (DocumentValidationError, ValueError):
        raise DocumentRepositoryError(_INVALID_RECORD_ERROR) from None


def _to_version(model: DocumentVersionModel) -> DocumentVersion:
    try:
        return DocumentVersion(
            version_id=model.version_id,
            document_id=model.document_id,
            checksum=model.checksum,
            source_uri=model.source_uri,
            source_updated_at=model.source_updated_at,
            security_level=SecurityLevel(model.security_level),
            ship_id=model.ship_id,
            project_id=model.project_id,
            department=model.department,
        )
    except (DocumentValidationError, ValueError):
        raise DocumentRepositoryError(_INVALID_RECORD_ERROR) from None


def _to_chunk(model: DocumentChunkModel) -> DocumentChunk:
    try:
        return DocumentChunk(
            chunk_id=model.chunk_id,
            version_id=model.version_id,
            structural_path=tuple(model.structural_path),
            ordinal=model.ordinal,
            normalized_text=model.normalized_text,
            page=model.page,
            section=model.section,
        )
    except (DocumentValidationError, ValueError):
        raise DocumentRepositoryError(_INVALID_RECORD_ERROR) from None


class PostgresDocumentRepository:
    """Insert and load document records in a caller-owned Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_document(self, document: Document) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(_to_document_model(document))
                self._session.flush()
        except IntegrityError:
            raise DocumentRepositoryError(_CONSTRAINT_ERROR) from None

    def get_document(self, document_id: UUID) -> Document | None:
        model = self._session.scalar(
            select(DocumentModel).where(DocumentModel.document_id == document_id)
        )
        return _to_document(model) if model is not None else None

    def find_document(
        self, source_system: str, source_id: str
    ) -> Document | None:
        model = self._session.scalar(
            select(DocumentModel).where(
                DocumentModel.source_system == source_system,
                DocumentModel.source_id == source_id,
            )
        )
        return _to_document(model) if model is not None else None

    def insert_version(self, version: DocumentVersion) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(_to_version_model(version))
                self._session.flush()
        except IntegrityError:
            raise DocumentRepositoryError(_CONSTRAINT_ERROR) from None

    def get_version(self, version_id: UUID) -> DocumentVersion | None:
        model = self._session.scalar(
            select(DocumentVersionModel).where(
                DocumentVersionModel.version_id == version_id
            )
        )
        return _to_version(model) if model is not None else None

    def find_version(
        self, document_id: UUID, checksum: str
    ) -> DocumentVersion | None:
        model = self._session.scalar(
            select(DocumentVersionModel).where(
                DocumentVersionModel.document_id == document_id,
                DocumentVersionModel.checksum == checksum,
            )
        )
        return _to_version(model) if model is not None else None

    def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        models = self._session.scalars(
            select(DocumentVersionModel)
            .where(DocumentVersionModel.document_id == document_id)
            .order_by(
                DocumentVersionModel.source_updated_at,
                DocumentVersionModel.version_id,
            )
        )
        return tuple(_to_version(model) for model in models)

    def insert_chunks(self, chunks: tuple[DocumentChunk, ...]) -> None:
        try:
            with self._session.begin_nested():
                self._session.add_all([_to_chunk_model(chunk) for chunk in chunks])
                self._session.flush()
        except IntegrityError:
            raise DocumentRepositoryError(_CONSTRAINT_ERROR) from None

    def list_chunks(self, version_id: UUID) -> tuple[DocumentChunk, ...]:
        models = self._session.scalars(
            select(DocumentChunkModel)
            .where(DocumentChunkModel.version_id == version_id)
            .order_by(
                DocumentChunkModel.structural_path,
                DocumentChunkModel.ordinal,
                DocumentChunkModel.chunk_id,
            )
        )
        return tuple(_to_chunk(model) for model in models)
