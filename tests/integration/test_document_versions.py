"""Integration coverage for document schema metadata and persistence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    inspect,
    literal,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres import (
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
    DomainRepository,
    PostgresDocumentRepository,
)
from packages.common import SecurityLevel
from packages.domain import (
    Document,
    DocumentChunk,
    DocumentVersion,
    Ship,
    document_chunk_id,
)
from services.ingestion import (
    DocumentRepositoryError,
    DocumentStore,
    DocumentVersionConflictError,
)

DOCUMENT_ID = UUID("91000000-0000-0000-0000-000000000001")
VERSION_A_ID = UUID("91000000-0000-0000-0000-000000000002")
VERSION_B_ID = UUID("91000000-0000-0000-0000-000000000003")
SHIP_ID = UUID("91000000-0000-0000-0000-000000000004")
PROJECT_ID = UUID("91000000-0000-0000-0000-000000000005")
UPDATED_AT = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)

type DocumentPersistenceModel = (
    DocumentModel | DocumentVersionModel | DocumentChunkModel
)


def _ship() -> Ship:
    return Ship(
        id=SHIP_ID,
        source_system="synthetic-mes",
        source_id="ship-task-009",
        source_updated_at=UPDATED_AT,
        ship_code="SYN-TASK-009",
    )


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
        "source_updated_at": UPDATED_AT,
        "security_level": SecurityLevel.INTERNAL,
        "ship_id": SHIP_ID,
        "project_id": PROJECT_ID,
        "department": "Synthetic Engineering",
    }
    values.update(changes)
    return DocumentVersion(**values)  # type: ignore[arg-type]


def _chunk(
    version_id: UUID,
    structural_path: tuple[str, ...],
    ordinal: int,
    **changes: object,
) -> DocumentChunk:
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


class _DocumentInsertBarrierRepository(PostgresDocumentRepository):
    """Coordinate two sessions after service pre-checks and before insert."""

    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def insert_document(self, document: Document) -> None:
        self._barrier.wait(timeout=30)
        super().insert_document(document)


class _VersionInsertBarrierRepository(PostgresDocumentRepository):
    """Coordinate two sessions after service pre-checks and before insert."""

    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def insert_version(self, version: DocumentVersion) -> None:
        self._barrier.wait(timeout=30)
        super().insert_version(version)


def _register_document_and_commit(
    engine: Engine,
    barrier: Barrier,
    document: Document,
) -> Document:
    with Session(engine) as session:
        store = DocumentStore(_DocumentInsertBarrierRepository(session, barrier))
        registered = store.register_document(document)
        session.commit()
        return registered


def _register_version_and_commit(
    engine: Engine,
    barrier: Barrier,
    version: DocumentVersion,
) -> DocumentVersion:
    with Session(engine) as session:
        store = DocumentStore(_VersionInsertBarrierRepository(session, barrier))
        registered = store.register_version(version)
        session.commit()
        return registered


def _invalid_persistence_model(case: str) -> DocumentPersistenceModel:
    record_id = UUID(
        {
            "document_source_system": "92000000-0000-0000-0000-000000000001",
            "document_source_id": "92000000-0000-0000-0000-000000000002",
            "document_title": "92000000-0000-0000-0000-000000000003",
            "version_uppercase_checksum": "92000000-0000-0000-0000-000000000004",
            "version_malformed_checksum": "92000000-0000-0000-0000-000000000005",
            "version_source_uri": "92000000-0000-0000-0000-000000000006",
            "version_security_level": "92000000-0000-0000-0000-000000000007",
            "version_department": "92000000-0000-0000-0000-000000000008",
            "chunk_null_path_element": "92000000-0000-0000-0000-000000000009",
            "chunk_empty_path_element": "92000000-0000-0000-0000-000000000010",
            "chunk_ordinal": "92000000-0000-0000-0000-000000000011",
            "chunk_text": "92000000-0000-0000-0000-000000000012",
            "chunk_page": "92000000-0000-0000-0000-000000000013",
            "chunk_section": "92000000-0000-0000-0000-000000000014",
        }[case]
    )
    if case.startswith("document_"):
        return DocumentModel(
            document_id=record_id,
            source_system=" " if case == "document_source_system" else "synthetic",
            source_id=" " if case == "document_source_id" else f"source-{record_id}",
            title=" " if case == "document_title" else "Synthetic title",
        )
    if case.startswith("version_"):
        return DocumentVersionModel(
            version_id=record_id,
            document_id=DOCUMENT_ID,
            checksum={
                "version_uppercase_checksum": "A" * 64,
                "version_malformed_checksum": "a" * 63,
            }.get(case, "c" * 64),
            source_uri=" " if case == "version_source_uri" else "synthetic://rule",
            source_updated_at=UPDATED_AT,
            security_level=4 if case == "version_security_level" else 1,
            ship_id=SHIP_ID,
            project_id=PROJECT_ID,
            department=" " if case == "version_department" else "Synthetic Quality",
        )
    structural_path = {
        "chunk_null_path_element": cast(list[str], [None]),
        "chunk_empty_path_element": [""],
    }.get(case, ["Chapter 1"])
    return DocumentChunkModel(
        chunk_id=record_id,
        version_id=VERSION_A_ID,
        structural_path=structural_path,
        ordinal=-1 if case == "chunk_ordinal" else 0,
        normalized_text=" " if case == "chunk_text" else "Synthetic text",
        page=0 if case == "chunk_page" else 1,
        section=" " if case == "chunk_section" else "Chapter 1",
    )


def test_document_metadata_declares_version_and_chunk_constraints() -> None:
    from infra.postgres import Base

    assert {"documents", "document_versions", "document_chunks"} <= set(
        Base.metadata.tables
    )
    assert {
        column.name for column in Base.metadata.tables["documents"].columns
    } == {"document_id", "source_system", "source_id", "title"}
    assert {
        column.name
        for column in Base.metadata.tables["document_versions"].columns
    } == {
        "version_id",
        "document_id",
        "checksum",
        "source_uri",
        "source_updated_at",
        "security_level",
        "ship_id",
        "project_id",
        "department",
    }
    assert {
        column.name
        for column in Base.metadata.tables["document_chunks"].columns
    } == {
        "chunk_id",
        "version_id",
        "structural_path",
        "ordinal",
        "normalized_text",
        "page",
        "section",
    }

    expected_unique_constraints = {
        "documents": {"uq_documents_source_identity"},
        "document_versions": {"uq_document_versions_document_checksum"},
        "document_chunks": {"uq_document_chunks_structural_location"},
    }
    expected_check_constraints = {
        "documents": {
            "ck_documents_source_system",
            "ck_documents_source_id",
            "ck_documents_title",
        },
        "document_versions": {
            "ck_document_versions_checksum",
            "ck_document_versions_source_uri",
            "ck_document_versions_security_level",
            "ck_document_versions_department",
        },
        "document_chunks": {
            "ck_document_chunks_path_elements",
            "ck_document_chunks_ordinal",
            "ck_document_chunks_text",
            "ck_document_chunks_page",
            "ck_document_chunks_section",
        },
    }
    expected_foreign_keys = {
        "document_versions": {
            "fk_document_versions_document_id": "documents.document_id",
            "fk_document_versions_ship_id": "ships.id",
        },
        "document_chunks": {
            "fk_document_chunks_version_id": "document_versions.version_id",
        },
    }
    expected_indexes = {
        "document_versions": {
            "ix_document_versions_document_id",
            "ix_document_versions_ship_id",
            "ix_document_versions_project_id",
            "ix_document_versions_department",
            "ix_document_versions_security_level",
        },
        "document_chunks": {
            "ix_document_chunks_version_id",
            "ix_document_chunks_page",
        },
    }

    for table_name, expected_names in expected_unique_constraints.items():
        table = Base.metadata.tables[table_name]
        assert {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        } == expected_names

    for table_name, expected_names in expected_check_constraints.items():
        table = Base.metadata.tables[table_name]
        assert {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        } == expected_names

    for table_name, expected_targets in expected_foreign_keys.items():
        table = Base.metadata.tables[table_name]
        assert {
            constraint.name: next(iter(constraint.elements)).target_fullname
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        } == expected_targets

    for table_name, expected_names in expected_indexes.items():
        table = Base.metadata.tables[table_name]
        assert {
            index.name for index in table.indexes if isinstance(index, Index)
        } == expected_names

    path_check = next(
        constraint
        for constraint in Base.metadata.tables["document_chunks"].constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_document_chunks_path_elements"
    )
    assert str(path_check.sqltext) == (
        "array_position(structural_path, NULL) IS NULL "
        "AND array_position(structural_path, '') IS NULL"
    )


def test_document_versions_and_chunks_round_trip_and_coexist(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    store = DocumentStore(repository)
    document = store.register_document(_document())
    first = store.register_version(_version())
    second = store.register_version(
        replace(
            _version(),
            version_id=VERSION_B_ID,
            checksum="b" * 64,
            source_uri="s3://synthetic-documents/rule-b.pdf",
            source_updated_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
            security_level=SecurityLevel.CONFIDENTIAL,
        )
    )
    chunks = (_chunk(first.version_id, ("Chapter 1",), 0),)
    store.add_chunks(first.version_id, chunks)

    assert store.get_document(document.document_id) == document
    assert store.list_versions(document.document_id) == (first, second)
    assert store.list_chunks(first.version_id) == chunks
    assert first.ship_id == SHIP_ID
    assert first.project_id == PROJECT_ID
    assert first.department == "Synthetic Engineering"


def test_concurrent_identical_document_registration_returns_one_stored_row(
    migrated_engine: Engine,
) -> None:
    document = _document()
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(
            executor.submit(
                _register_document_and_commit,
                migrated_engine,
                barrier,
                document,
            )
            for _ in range(2)
        )
        registered = tuple(future.result(timeout=30) for future in futures)

    with Session(migrated_engine) as session:
        stored = PostgresDocumentRepository(session).get_document(document.document_id)
        rows = tuple(session.scalars(select(DocumentModel)))

    assert stored == document
    assert registered == (stored, stored)
    assert len(rows) == 1


def test_concurrent_identical_checksum_registration_returns_one_stored_version(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        DomainRepository(session).insert(_ship())
        PostgresDocumentRepository(session).insert_document(_document())
        session.commit()

    first_proposal = _version()
    second_proposal = replace(first_proposal, version_id=VERSION_B_ID)
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                _register_version_and_commit,
                migrated_engine,
                barrier,
                first_proposal,
            ),
            executor.submit(
                _register_version_and_commit,
                migrated_engine,
                barrier,
                second_proposal,
            ),
        )
        registered = tuple(future.result(timeout=30) for future in futures)

    with Session(migrated_engine) as session:
        stored = PostgresDocumentRepository(session).find_version(
            DOCUMENT_ID, first_proposal.checksum
        )
        rows = tuple(session.scalars(select(DocumentVersionModel)))

    assert stored is not None
    assert registered == (stored, stored)
    assert stored.version_id in {VERSION_A_ID, VERSION_B_ID}
    assert len(rows) == 1


def test_repository_leaves_transaction_ownership_with_caller(
    migrated_session: Session,
) -> None:
    repository = PostgresDocumentRepository(migrated_session)
    store = DocumentStore(repository)
    registered = store.register_document(_document())

    assert store.get_document(registered.document_id) == registered
    migrated_session.rollback()

    assert store.get_document(registered.document_id) is None


def test_duplicate_document_source_identity_is_safe_and_preserves_first_row(
    migrated_session: Session,
) -> None:
    repository = PostgresDocumentRepository(migrated_session)
    first = _document()
    repository.insert_document(first)
    rejected = _document(
        document_id=UUID("91000000-0000-0000-0000-000000000010"),
        title="Rejected synthetic title",
    )

    with pytest.raises(DocumentRepositoryError) as captured:
        repository.insert_document(rejected)

    assert str(captured.value) == "document record violates persistence constraints"
    assert rejected.source_id not in str(captured.value)
    assert rejected.title not in str(captured.value)
    assert repository.find_document(first.source_system, first.source_id) == first
    assert repository.get_document(rejected.document_id) is None


def test_direct_duplicate_checksum_is_safe_and_preserves_first_version(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    first = _version()
    repository.insert_version(first)
    rejected_department = "Synthetic Sensitive Department"
    rejected = replace(
        first,
        version_id=UUID("91000000-0000-0000-0000-000000000011"),
        source_uri="s3://synthetic-documents/rejected-rule.pdf",
        department=rejected_department,
    )

    with pytest.raises(DocumentRepositoryError) as captured:
        repository.insert_version(rejected)

    assert str(captured.value) == "document record violates persistence constraints"
    for sensitive_value in (
        rejected.checksum,
        rejected.source_uri,
        rejected_department,
    ):
        assert sensitive_value not in str(captured.value)
    assert repository.find_version(first.document_id, first.checksum) == first
    assert repository.get_version(rejected.version_id) is None


@pytest.mark.parametrize("missing_parent", ["document", "ship"])
def test_missing_version_parent_is_safe_and_session_recovers(
    migrated_session: Session,
    missing_parent: str,
) -> None:
    missing_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    domain_repository = DomainRepository(migrated_session)
    repository = PostgresDocumentRepository(migrated_session)
    original = _version()
    if missing_parent == "document":
        domain_repository.insert(_ship())
        rejected = replace(original, document_id=missing_id)
    else:
        repository.insert_document(_document())
        rejected = replace(original, ship_id=missing_id)

    with pytest.raises(DocumentRepositoryError) as captured:
        repository.insert_version(rejected)

    assert str(captured.value) == "document record violates persistence constraints"
    assert str(missing_id) not in str(captured.value)
    if missing_parent == "document":
        repository.insert_document(_document())
    else:
        domain_repository.insert(_ship())
    repository.insert_version(original)
    assert repository.get_version(original.version_id) == original


def test_chunk_batch_is_atomic_and_session_remains_usable(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    repository.insert_version(_version())
    valid = _chunk(VERSION_A_ID, ("Chapter 1",), 0)
    missing_version_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    rejected = _chunk(
        missing_version_id,
        ("Rejected",),
        0,
        normalized_text="Sensitive rejected chunk text.",
    )

    with pytest.raises(DocumentRepositoryError) as captured:
        repository.insert_chunks((valid, rejected))

    assert str(captured.value) == "document record violates persistence constraints"
    assert rejected.normalized_text not in str(captured.value)
    assert repository.list_chunks(VERSION_A_ID) == ()
    assert migrated_session.scalar(select(literal(1))) == 1


def test_corrupt_nondeterministic_chunk_id_fails_safe_reconstruction(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    repository.insert_version(_version())
    corrupted_id = UUID("91000000-0000-0000-0000-000000000020")
    sensitive_text = "Sensitive corrupt chunk text."
    migrated_session.add(
        DocumentChunkModel(
            chunk_id=corrupted_id,
            version_id=VERSION_A_ID,
            structural_path=["Chapter 9"],
            ordinal=0,
            normalized_text=sensitive_text,
            page=9,
            section="Chapter 9",
        )
    )
    migrated_session.flush()

    with pytest.raises(DocumentRepositoryError) as captured:
        repository.list_chunks(VERSION_A_ID)

    assert str(captured.value) == "stored document record is invalid"
    assert str(corrupted_id) not in str(captured.value)
    assert sensitive_text not in str(captured.value)


@pytest.mark.parametrize(
    "case",
    [
        "document_source_system",
        "document_source_id",
        "document_title",
        "version_uppercase_checksum",
        "version_malformed_checksum",
        "version_source_uri",
        "version_security_level",
        "version_department",
        "chunk_null_path_element",
        "chunk_empty_path_element",
        "chunk_ordinal",
        "chunk_text",
        "chunk_page",
        "chunk_section",
    ],
)
def test_postgresql_rejects_document_constraint_violations(
    migrated_session: Session,
    case: str,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    repository.insert_version(_version())

    with pytest.raises(IntegrityError), migrated_session.begin_nested():
        migrated_session.add(_invalid_persistence_model(case))
        migrated_session.flush()

    assert migrated_session.scalar(select(literal(1))) == 1


def test_version_retry_is_exact_and_metadata_conflict_inserts_no_row(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    store = DocumentStore(repository)
    store.register_document(_document())
    first = store.register_version(_version())
    second = store.register_version(
        replace(
            first,
            version_id=VERSION_B_ID,
            checksum="b" * 64,
            source_uri="s3://synthetic-documents/rule-b.pdf",
            source_updated_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        )
    )
    retry = replace(
        first,
        version_id=UUID("91000000-0000-0000-0000-000000000030"),
    )
    assert store.register_version(retry) == first
    rejected_uri = "s3://synthetic-documents/conflicting-sensitive-rule.pdf"

    with pytest.raises(DocumentVersionConflictError) as captured:
        store.register_version(
            replace(
                retry,
                version_id=UUID("91000000-0000-0000-0000-000000000031"),
                source_uri=rejected_uri,
            )
        )

    assert str(captured.value) == "document version metadata conflicts"
    assert rejected_uri not in str(captured.value)
    assert store.list_versions(DOCUMENT_ID) == (first, second)


def test_repository_lists_versions_and_chunks_in_deterministic_order(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    first = _version()
    second = replace(
        first,
        version_id=VERSION_B_ID,
        checksum="b" * 64,
        source_uri="s3://synthetic-documents/rule-b.pdf",
    )
    repository.insert_version(second)
    repository.insert_version(first)
    path_a_0 = _chunk(VERSION_A_ID, ("Chapter 1", "A"), 0)
    path_a_1 = _chunk(VERSION_A_ID, ("Chapter 1", "A"), 1)
    path_z = _chunk(VERSION_A_ID, ("Chapter 1", "Z"), 0)
    repository.insert_chunks((path_z, path_a_1, path_a_0))

    assert repository.list_versions(DOCUMENT_ID) == (first, second)
    assert repository.list_chunks(VERSION_A_ID) == (path_a_0, path_a_1, path_z)


def test_postgresql_rejects_duplicate_chunk_structural_location(
    migrated_session: Session,
) -> None:
    DomainRepository(migrated_session).insert(_ship())
    repository = PostgresDocumentRepository(migrated_session)
    repository.insert_document(_document())
    repository.insert_version(_version())
    first = _chunk(VERSION_A_ID, ("Chapter 1", "Scope"), 0)
    repository.insert_chunks((first,))

    with pytest.raises(IntegrityError), migrated_session.begin_nested():
        migrated_session.add(
            DocumentChunkModel(
                chunk_id=UUID("91000000-0000-0000-0000-000000000040"),
                version_id=first.version_id,
                structural_path=list(first.structural_path),
                ordinal=first.ordinal,
                normalized_text="Rejected duplicate structural location.",
                page=2,
                section="Scope",
            )
        )
        migrated_session.flush()

    assert repository.list_chunks(VERSION_A_ID) == (first,)


def test_document_migration_is_current_head(migrated_engine: Engine) -> None:
    assert {"documents", "document_versions", "document_chunks"} <= set(
        inspect(migrated_engine).get_table_names()
    )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "20260819_0003"
        )
