"""Tests for immutable DocumentStore behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from packages.common import DocumentType, SecurityLevel
from packages.domain import Document, DocumentChunk, DocumentVersion, document_chunk_id
from services.ingestion.document_store import (
    DocumentChunkConflictError,
    DocumentConflictError,
    DocumentNotFoundError,
    DocumentRepository,
    DocumentRepositoryError,
    DocumentStore,
    DocumentVersionConflictError,
    DocumentVersionNotFoundError,
)

DOCUMENT_ID = UUID("90000000-0000-0000-0000-000000000001")
DOCUMENT_CONFLICT_ID = UUID("90000000-0000-0000-0000-000000000010")
VERSION_A_ID = UUID("90000000-0000-0000-0000-000000000002")
VERSION_B_ID = UUID("90000000-0000-0000-0000-000000000011")
VERSION_RETRY_ID = UUID("90000000-0000-0000-0000-000000000012")
SHIP_ID = UUID("90000000-0000-0000-0000-000000000003")
PROJECT_ID = UUID("90000000-0000-0000-0000-000000000004")
UPDATED_AT = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


class _MemoryDocumentRepository:
    """Deterministic in-memory port fake for service behavior tests."""

    def __init__(self) -> None:
        self.documents_by_id: dict[UUID, Document] = {}
        self.documents_by_source: dict[tuple[str, str], Document] = {}
        self.versions_by_id: dict[UUID, DocumentVersion] = {}
        self.versions_by_checksum: dict[tuple[UUID, str], DocumentVersion] = {}
        self.chunks_by_version: dict[UUID, list[DocumentChunk]] = {}
        self.document_writes = 0
        self.version_writes = 0
        self.chunk_writes: list[tuple[DocumentChunk, ...]] = []

    def insert_document(self, document: Document) -> None:
        self.documents_by_id[document.document_id] = document
        self.documents_by_source[(document.source_system, document.source_id)] = (
            document
        )
        self.document_writes += 1

    def get_document(self, document_id: UUID) -> Document | None:
        return self.documents_by_id.get(document_id)

    def find_document(
        self, source_system: str, source_id: str
    ) -> Document | None:
        return self.documents_by_source.get((source_system, source_id))

    def insert_version(self, version: DocumentVersion) -> None:
        self.versions_by_id[version.version_id] = version
        self.versions_by_checksum[(version.document_id, version.checksum)] = version
        self.version_writes += 1

    def get_version(self, version_id: UUID) -> DocumentVersion | None:
        return self.versions_by_id.get(version_id)

    def find_version(
        self, document_id: UUID, checksum: str
    ) -> DocumentVersion | None:
        return self.versions_by_checksum.get((document_id, checksum))

    def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        return tuple(
            version
            for version in self.versions_by_id.values()
            if version.document_id == document_id
        )

    def insert_chunks(self, chunks: tuple[DocumentChunk, ...]) -> None:
        self.chunk_writes.append(chunks)
        for chunk in chunks:
            self.chunks_by_version.setdefault(chunk.version_id, []).append(chunk)

    def list_chunks(self, version_id: UUID) -> tuple[DocumentChunk, ...]:
        return tuple(self.chunks_by_version.get(version_id, []))


class _DocumentInsertFailureRepository(_MemoryDocumentRepository):
    """Expose a concurrent Document winner before an insert failure returns."""

    def __init__(
        self,
        *,
        winner: Document | None,
        failure: DocumentRepositoryError,
    ) -> None:
        super().__init__()
        self._winner = winner
        self._failure = failure

    def insert_document(self, document: Document) -> None:
        if self._winner is not None:
            super().insert_document(self._winner)
        raise self._failure


class _VersionInsertFailureRepository(_MemoryDocumentRepository):
    """Expose a concurrent Version winner before an insert failure returns."""

    def __init__(
        self,
        *,
        winner: DocumentVersion | None,
        failure: DocumentRepositoryError,
    ) -> None:
        super().__init__()
        self._winner = winner
        self._failure = failure

    def insert_version(self, version: DocumentVersion) -> None:
        if self._winner is not None:
            super().insert_version(self._winner)
        raise self._failure


def _document(**changes: object) -> Document:
    values: dict[str, object] = {
        "document_id": DOCUMENT_ID,
        "source_system": "synthetic-plm",
        "source_id": "rule-a",
        "title": "Synthetic Class Rule A",
    }
    values.update(changes)
    return Document(**values)  # type: ignore[arg-type]


def _version(**changes: object) -> DocumentVersion:
    values: dict[str, object] = {
        "version_id": VERSION_A_ID,
        "document_id": DOCUMENT_ID,
        "checksum": "a" * 64,
        "source_uri": "s3://synthetic-documents/rule-a.pdf",
        "document_type": DocumentType.PDF,
        "source_updated_at": UPDATED_AT,
        "security_level": SecurityLevel.INTERNAL,
        "ship_id": SHIP_ID,
        "project_id": PROJECT_ID,
        "department": "Synthetic Engineering",
    }
    values.update(changes)
    return DocumentVersion(**values)  # type: ignore[arg-type]


def _chunk(
    *, version_id: UUID = VERSION_A_ID, ordinal: int = 0, **changes: object
) -> DocumentChunk:
    structural_path = cast(
        tuple[str, ...], changes.pop("structural_path", ("Chapter 1", "Scope"))
    )
    values: dict[str, object] = {
        "chunk_id": document_chunk_id(version_id, structural_path, ordinal),
        "version_id": version_id,
        "structural_path": structural_path,
        "ordinal": ordinal,
        "normalized_text": "Synthetic class-rule paragraph.",
        "page": 1,
        "section": "Chapter 1",
    }
    values.update(changes)
    return DocumentChunk(**values)  # type: ignore[arg-type]


def test_register_version_is_idempotent_and_preserves_immutable_record() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    document = _document()
    original = _version(version_id=VERSION_A_ID, checksum="a" * 64)
    retry = replace(original, version_id=VERSION_RETRY_ID)

    assert store.register_document(document) == document
    assert store.register_version(original) == original
    assert store.register_version(retry) == original
    assert store.list_versions(document.document_id) == (original,)


def test_register_version_rejects_document_type_change_for_checksum_retry() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    store.register_document(_document())
    original = store.register_version(_version())

    with pytest.raises(
        DocumentVersionConflictError,
        match="^document version metadata conflicts$",
    ):
        store.register_version(
            replace(
                original,
                version_id=VERSION_RETRY_ID,
                document_type=DocumentType.DOCX,
            )
        )

    assert store.list_versions(DOCUMENT_ID) == (original,)


def test_versions_with_different_checksums_coexist() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    document = store.register_document(_document())
    first = store.register_version(_version(checksum="a" * 64))
    second = store.register_version(
        _version(version_id=VERSION_B_ID, checksum="b" * 64)
    )

    assert store.list_versions(document.document_id) == (first, second)


def test_register_document_returns_exact_winner_after_insert_race() -> None:
    proposed = _document()
    winner = replace(proposed)
    repository = _DocumentInsertFailureRepository(
        winner=winner,
        failure=DocumentRepositoryError("synthetic document insert race"),
    )

    assert DocumentStore(repository).register_document(proposed) is winner


@pytest.mark.parametrize(
    "winner",
    [
        replace(_document(), source_id="occupied-other-source"),
        replace(_document(), document_id=DOCUMENT_CONFLICT_ID),
    ],
)
def test_register_document_maps_raced_identity_conflict_to_domain_error(
    winner: Document,
) -> None:
    repository = _DocumentInsertFailureRepository(
        winner=winner,
        failure=DocumentRepositoryError("synthetic document insert race"),
    )

    with pytest.raises(
        DocumentConflictError, match="^document source identity conflicts$"
    ):
        DocumentStore(repository).register_document(_document())


def test_register_document_reraises_unrelated_insert_failure() -> None:
    failure = DocumentRepositoryError("synthetic unrelated document failure")
    repository = _DocumentInsertFailureRepository(winner=None, failure=failure)

    with pytest.raises(DocumentRepositoryError) as captured:
        DocumentStore(repository).register_document(_document())

    assert captured.value is failure


def test_register_version_returns_exact_checksum_winner_after_insert_race() -> None:
    proposed = _version()
    winner = replace(proposed, version_id=VERSION_RETRY_ID)
    repository = _VersionInsertFailureRepository(
        winner=winner,
        failure=DocumentRepositoryError("synthetic version insert race"),
    )
    repository.insert_document(_document())

    assert DocumentStore(repository).register_version(proposed) is winner


@pytest.mark.parametrize(
    "winner",
    [
        replace(_version(), checksum="b" * 64),
        replace(
            _version(),
            version_id=VERSION_RETRY_ID,
            source_uri="s3://synthetic-documents/conflicting-race.pdf",
        ),
    ],
)
def test_register_version_maps_raced_identity_conflict_to_domain_error(
    winner: DocumentVersion,
) -> None:
    repository = _VersionInsertFailureRepository(
        winner=winner,
        failure=DocumentRepositoryError("synthetic version insert race"),
    )
    repository.insert_document(_document())

    with pytest.raises(
        DocumentVersionConflictError,
        match="^document version metadata conflicts$",
    ):
        DocumentStore(repository).register_version(_version())


def test_register_version_reraises_unrelated_insert_failure() -> None:
    failure = DocumentRepositoryError("synthetic unrelated version failure")
    repository = _VersionInsertFailureRepository(winner=None, failure=failure)
    repository.insert_document(_document())

    with pytest.raises(DocumentRepositoryError) as captured:
        DocumentStore(repository).register_version(_version())

    assert captured.value is failure


@pytest.mark.parametrize(
    "conflicting_document",
    [
        _document(document_id=DOCUMENT_CONFLICT_ID),
        _document(title="Conflicting title"),
    ],
)
def test_register_document_rejects_conflicting_source_identity(
    conflicting_document: Document,
) -> None:
    store = DocumentStore(_MemoryDocumentRepository())
    assert store.register_document(_document()) == _document()

    with pytest.raises(
        DocumentConflictError, match="^document source identity conflicts$"
    ):
        store.register_document(conflicting_document)


@pytest.mark.parametrize(
    "changed_version",
    [
        _version(source_uri="s3://synthetic-documents/rule-a-revised.pdf"),
        _version(source_updated_at=UPDATED_AT + timedelta(seconds=1)),
        _version(security_level=SecurityLevel.CONFIDENTIAL),
        _version(ship_id=None),
        _version(project_id=None),
        _version(department="Synthetic Quality"),
    ],
)
def test_register_version_rejects_conflicting_immutable_metadata(
    changed_version: DocumentVersion,
) -> None:
    store = DocumentStore(_MemoryDocumentRepository())
    store.register_document(_document())
    store.register_version(_version())

    with pytest.raises(
        DocumentVersionConflictError,
        match="^document version metadata conflicts$",
    ):
        store.register_version(changed_version)


def test_register_version_rejects_occupied_version_id_with_new_checksum() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    original = _version()
    store.register_document(_document())
    store.register_version(original)

    with pytest.raises(
        DocumentVersionConflictError,
        match="^document version metadata conflicts$",
    ):
        store.register_version(replace(original, checksum="b" * 64))

    assert repository.version_writes == 1
    assert store.list_versions(DOCUMENT_ID) == (original,)


def test_register_version_rejects_checksum_retry_with_occupied_version_id() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    store.register_document(_document())
    checksum_winner = store.register_version(_version())
    id_occupier = store.register_version(
        replace(
            checksum_winner,
            version_id=VERSION_B_ID,
            checksum="b" * 64,
            source_uri="s3://synthetic-documents/rule-b.pdf",
        )
    )
    stored_before = store.list_versions(DOCUMENT_ID)
    writes_before = repository.version_writes
    proposed = replace(checksum_winner, version_id=id_occupier.version_id)

    with pytest.raises(
        DocumentVersionConflictError,
        match="^document version metadata conflicts$",
    ):
        store.register_version(proposed)

    assert repository.version_writes == writes_before
    assert store.list_versions(DOCUMENT_ID) == stored_before


def test_register_version_requires_document_without_writing() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)

    with pytest.raises(DocumentNotFoundError, match="^document does not exist$"):
        store.register_version(_version())

    assert repository.version_writes == 0


def test_add_chunks_requires_version_without_writing() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)

    with pytest.raises(
        DocumentVersionNotFoundError, match="^document version does not exist$"
    ):
        store.add_chunks(VERSION_A_ID, (_chunk(),))

    assert repository.chunk_writes == []


@pytest.mark.parametrize(
    "chunks",
    [
        (_chunk(), _chunk(version_id=VERSION_B_ID)),
        (_chunk(), _chunk()),
    ],
)
def test_add_chunks_rejects_conflicting_batch(
    chunks: tuple[DocumentChunk, ...],
) -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    store.register_document(_document())
    store.register_version(_version())

    with pytest.raises(
        DocumentChunkConflictError, match="^document chunk batch conflicts$"
    ):
        store.add_chunks(VERSION_A_ID, chunks)

    assert repository.chunk_writes == []


def test_add_chunks_inserts_one_valid_immutable_tuple_once() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)
    store.register_document(_document())
    store.register_version(_version())
    chunks = (_chunk(), _chunk(ordinal=1))

    store.add_chunks(VERSION_A_ID, chunks)
    assert repository.chunk_writes == [chunks]
    assert store.list_chunks(VERSION_A_ID) == chunks


def test_add_chunks_with_empty_tuple_is_a_noop() -> None:
    repository = _MemoryDocumentRepository()
    store = DocumentStore(repository)

    store.add_chunks(VERSION_A_ID, ())
    assert repository.chunk_writes == []


def test_store_and_repository_have_no_mutating_members() -> None:
    for member in ("update", "delete", "upsert", "commit"):
        assert not hasattr(DocumentStore, member)
        assert not hasattr(DocumentRepository, member)
