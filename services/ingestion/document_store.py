"""Immutable document metadata registration service and repository port."""

from typing import Protocol
from uuid import UUID

from packages.domain import Document, DocumentChunk, DocumentVersion


class DocumentStoreError(RuntimeError):
    """Base error for immutable document-store operations."""


class DocumentRepositoryError(DocumentStoreError):
    """Raised when a document repository cannot complete an operation."""


class DocumentConflictError(DocumentStoreError):
    """Raised when a document source identity conflicts with stored data."""


class DocumentVersionConflictError(DocumentStoreError):
    """Raised when immutable version metadata conflicts with stored data."""


class DocumentChunkConflictError(DocumentStoreError):
    """Raised when a chunk batch is internally inconsistent."""


class DocumentNotFoundError(DocumentStoreError):
    """Raised when a referenced document is not registered."""


class DocumentVersionNotFoundError(DocumentStoreError):
    """Raised when a referenced document version is not registered."""


class DocumentRepository(Protocol):
    """Insert/read-only persistence boundary for immutable document records."""

    def insert_document(self, document: Document) -> None: ...

    def get_document(self, document_id: UUID) -> Document | None: ...

    def find_document(
        self, source_system: str, source_id: str
    ) -> Document | None: ...

    def insert_version(self, version: DocumentVersion) -> None: ...

    def get_version(self, version_id: UUID) -> DocumentVersion | None: ...

    def find_version(
        self, document_id: UUID, checksum: str
    ) -> DocumentVersion | None: ...

    def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]: ...

    def insert_chunks(self, chunks: tuple[DocumentChunk, ...]) -> None: ...

    def list_chunks(self, version_id: UUID) -> tuple[DocumentChunk, ...]: ...


class DocumentStore:
    """Register immutable document evidence through a caller-owned repository."""

    def __init__(self, repository: DocumentRepository) -> None:
        self._repository = repository

    def register_document(self, document: Document) -> Document:
        """Register a stable document identity or return its exact retry."""
        by_id = self._repository.get_document(document.document_id)
        by_source = self._repository.find_document(
            document.source_system, document.source_id
        )
        if by_id is None and by_source is None:
            try:
                self._repository.insert_document(document)
            except DocumentRepositoryError:
                by_id = self._repository.get_document(document.document_id)
                by_source = self._repository.find_document(
                    document.source_system, document.source_id
                )
                if by_id == document and by_source == document:
                    return by_source
                if by_id is not None or by_source is not None:
                    raise DocumentConflictError(
                        "document source identity conflicts"
                    ) from None
                raise
            return document
        if by_id == document and by_source == document:
            return document
        raise DocumentConflictError("document source identity conflicts")

    def register_version(self, version: DocumentVersion) -> DocumentVersion:
        """Register one immutable version or return an exact checksum retry."""
        if self._repository.get_document(version.document_id) is None:
            raise DocumentNotFoundError("document does not exist")

        by_id = self._repository.get_version(version.version_id)
        by_checksum = self._repository.find_version(
            version.document_id, version.checksum
        )
        if by_checksum is not None:
            if (
                self._version_payload(by_checksum) == self._version_payload(version)
                and (by_id is None or by_id == by_checksum)
            ):
                return by_checksum
            raise DocumentVersionConflictError("document version metadata conflicts")
        if by_id is not None:
            raise DocumentVersionConflictError("document version metadata conflicts")

        try:
            self._repository.insert_version(version)
        except DocumentRepositoryError:
            by_id = self._repository.get_version(version.version_id)
            by_checksum = self._repository.find_version(
                version.document_id, version.checksum
            )
            if (
                by_checksum is not None
                and self._version_payload(by_checksum) == self._version_payload(version)
                and (by_id is None or by_id == by_checksum)
            ):
                return by_checksum
            if by_id is not None or by_checksum is not None:
                raise DocumentVersionConflictError(
                    "document version metadata conflicts"
                ) from None
            raise
        return version

    def add_chunks(
        self, version_id: UUID, chunks: tuple[DocumentChunk, ...]
    ) -> None:
        """Atomically add a valid, version-local chunk batch."""
        if not chunks:
            return
        if self._repository.get_version(version_id) is None:
            raise DocumentVersionNotFoundError("document version does not exist")

        chunk_ids = {chunk.chunk_id for chunk in chunks}
        locations = {
            (chunk.version_id, chunk.structural_path, chunk.ordinal) for chunk in chunks
        }
        if (
            any(chunk.version_id != version_id for chunk in chunks)
            or len(chunk_ids) != len(chunks)
            or len(locations) != len(chunks)
        ):
            raise DocumentChunkConflictError("document chunk batch conflicts")
        self._repository.insert_chunks(chunks)

    def get_document(self, document_id: UUID) -> Document | None:
        """Get one document by canonical ID."""
        return self._repository.get_document(document_id)

    def get_version(self, version_id: UUID) -> DocumentVersion | None:
        """Get one document version by canonical ID."""
        return self._repository.get_version(version_id)

    def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        """List immutable versions for a document."""
        return self._repository.list_versions(document_id)

    def list_chunks(self, version_id: UUID) -> tuple[DocumentChunk, ...]:
        """List immutable chunks for a document version."""
        return self._repository.list_chunks(version_id)

    @staticmethod
    def _version_payload(version: DocumentVersion) -> tuple[object, ...]:
        return (
            version.document_id,
            version.checksum,
            version.source_uri,
            version.source_updated_at,
            version.security_level,
            version.ship_id,
            version.project_id,
            version.department,
        )
