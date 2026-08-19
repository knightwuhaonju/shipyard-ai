"""Integration coverage for document schema metadata and migrations."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import Engine


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
