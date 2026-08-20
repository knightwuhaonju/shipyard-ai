"""Integration coverage for deterministic pgvector embedding storage."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres import (
    DATABASE_EMBEDDING_DIMENSION,
    DATABASE_EMBEDDING_MODEL_ID,
    DocumentChunkEmbeddingModel,
    EmbeddingPersistenceError,
    PostgresEmbeddingRepository,
)
from services.model_gateway import EmbeddingProfile
from tests.integration.postgres_support import (
    alembic_config,
    configured_test_database_url,
    downgrade_to_base,
    validated_alembic_test_database_url,
)

DOCUMENT_ID = UUID("94000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("94000000-0000-0000-0000-000000000002")
CHUNK_A_ID = UUID("94000000-0000-0000-0000-000000000003")
CHUNK_B_ID = UUID("94000000-0000-0000-0000-000000000004")
MISSING_CHUNK_ID = UUID("94000000-0000-0000-0000-000000000005")
PROFILE = EmbeddingProfile(
    model_id="fake-deterministic-v1",
    dimension=8,
)
VECTOR_A = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
VECTOR_B = (0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
PERSISTENCE_ERROR = "embedding record violates persistence constraints"


def _insert_chunks(session: Session, *chunk_ids: UUID) -> None:
    session.execute(
        text(
            "INSERT INTO documents "
            "(document_id, source_system, source_id, title) "
            "VALUES (:document_id, 'synthetic-plm', 'vector-rule', "
            "'Synthetic vector rule')"
        ),
        {"document_id": DOCUMENT_ID},
    )
    session.execute(
        text(
            "INSERT INTO document_versions "
            "(version_id, document_id, checksum, source_uri, document_type, "
            "source_updated_at, security_level) "
            "VALUES (:version_id, :document_id, :checksum, "
            "'s3://synthetic/vector-rule.pdf', 'pdf', "
            "'2026-08-20T08:00:00+00:00', 0)"
        ),
        {
            "version_id": VERSION_ID,
            "document_id": DOCUMENT_ID,
            "checksum": "9" * 64,
        },
    )
    for ordinal, chunk_id in enumerate(chunk_ids):
        session.execute(
            text(
                "INSERT INTO document_chunks "
                "(chunk_id, version_id, structural_path, ordinal, "
                "normalized_text, page, section) "
                "VALUES (:chunk_id, :version_id, ARRAY[:section], :ordinal, "
                ":normalized_text, 1, :section)"
            ),
            {
                "chunk_id": chunk_id,
                "version_id": VERSION_ID,
                "ordinal": ordinal,
                "normalized_text": f"Synthetic vector paragraph {ordinal}.",
                "section": f"Section {ordinal}",
            },
        )
    session.flush()


def _embedding_count(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(DocumentChunkEmbeddingModel)
    ) or 0


def test_vector_metadata_declares_exact_profile_table_and_indexes() -> None:
    table = cast(Table, DocumentChunkEmbeddingModel.__table__)

    assert DATABASE_EMBEDDING_DIMENSION == 8
    assert DATABASE_EMBEDDING_MODEL_ID == "fake-deterministic-v1"
    assert table.name == "document_chunk_embeddings"
    assert set(table.primary_key.columns.keys()) == {
        "chunk_id",
        "embedding_model",
    }
    assert {column.name for column in table.columns} == {
        "chunk_id",
        "embedding_model",
        "embedding",
    }
    assert str(table.c.embedding.type).upper() == "VECTOR(8)"
    assert {index.name for index in table.indexes} >= {
        "ix_document_chunk_embeddings_model",
        "ix_document_chunk_embeddings_hnsw_cosine",
    }
    hnsw = next(
        index
        for index in table.indexes
        if index.name == "ix_document_chunk_embeddings_hnsw_cosine"
    )
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }


def test_vector_metadata_declares_named_fk_and_database_checks() -> None:
    table = cast(Table, DocumentChunkEmbeddingModel.__table__)
    foreign_keys = {
        constraint.name: tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert foreign_keys == {
        "fk_document_chunk_embeddings_chunk_id": ("document_chunks.chunk_id",)
    }
    assert set(checks) == {
        "ck_document_chunk_embeddings_model",
        "ck_document_chunk_embeddings_nonzero",
    }
    assert "btrim(embedding_model) <> ''" in checks[
        "ck_document_chunk_embeddings_model"
    ]
    assert "vector_norm(embedding) > 0" in checks[
        "ck_document_chunk_embeddings_nonzero"
    ]


def test_vector_migration_is_current_head(migrated_engine: Engine) -> None:
    assert "document_chunk_embeddings" in inspect(migrated_engine).get_table_names()
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "20260820_0005"
        )


def test_vector_migration_creates_exact_schema_and_index_methods(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    columns = {
        column["name"]: (str(column["type"]).upper(), column["nullable"])
        for column in inspector.get_columns("document_chunk_embeddings")
    }

    assert columns == {
        "chunk_id": ("UUID", False),
        "embedding_model": ("TEXT", False),
        "embedding": ("VECTOR(8)", False),
    }
    primary_key_columns = inspector.get_pk_constraint(
        "document_chunk_embeddings"
    )["constrained_columns"]
    assert set(primary_key_columns) == {
        "chunk_id",
        "embedding_model",
    }
    assert {
        foreign_key["name"]: tuple(foreign_key["referred_columns"])
        for foreign_key in inspector.get_foreign_keys("document_chunk_embeddings")
    } == {"fk_document_chunk_embeddings_chunk_id": ("chunk_id",)}
    assert {
        check["name"]
        for check in inspector.get_check_constraints("document_chunk_embeddings")
    } == {
        "ck_document_chunk_embeddings_model",
        "ck_document_chunk_embeddings_nonzero",
    }
    with migrated_engine.connect() as connection:
        assert connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()
        index_definitions = {
            row.indexname: row.indexdef
            for row in connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = 'document_chunk_embeddings'"
                )
            )
        }
    assert "USING btree (embedding_model)" in index_definitions[
        "ix_document_chunk_embeddings_model"
    ]
    assert "USING hnsw (embedding vector_cosine_ops)" in index_definitions[
        "ix_document_chunk_embeddings_hnsw_cosine"
    ]


def test_vector_migration_offline_sql_contains_extension_table_and_hnsw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = alembic_config(configured_test_database_url())

    command.upgrade(config, "head", sql=True)

    sql = capsys.readouterr().out.lower()
    assert "create extension if not exists vector" in sql
    assert "create table document_chunk_embeddings" in sql
    assert "vector(8)" in sql
    assert "using hnsw (embedding vector_cosine_ops)" in sql


def test_vector_migration_downgrade_removes_table_but_retains_extension() -> None:
    url = configured_test_database_url()
    config = alembic_config(url)
    database_engine = create_engine(url)
    try:
        downgrade_to_base(config)
        command.upgrade(config, "head")

        validated_alembic_test_database_url(config)
        command.downgrade(config, "20260820_0004")

        assert "document_chunk_embeddings" not in inspect(
            database_engine
        ).get_table_names()
        with database_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    ")"
                )
            ).scalar_one()

        command.upgrade(config, "head")
        assert "document_chunk_embeddings" in inspect(
            database_engine
        ).get_table_names()
    finally:
        database_engine.dispose()
        downgrade_to_base(config)


def test_repository_inserts_valid_embedding_without_committing(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        _insert_chunks(session, CHUNK_A_ID)
        repository = PostgresEmbeddingRepository(session, PROFILE)

        repository.insert(CHUNK_A_ID, VECTOR_A)

        stored = session.get(
            DocumentChunkEmbeddingModel,
            (CHUNK_A_ID, DATABASE_EMBEDDING_MODEL_ID),
        )
        assert stored is not None
        assert tuple(stored.embedding) == pytest.approx(VECTOR_A)
        session.rollback()

    with Session(migrated_engine) as verification_session:
        assert _embedding_count(verification_session) == 0


def test_database_allows_same_chunk_for_distinct_embedding_models(
    migrated_session: Session,
) -> None:
    _insert_chunks(migrated_session, CHUNK_A_ID)
    migrated_session.add_all(
        [
            DocumentChunkEmbeddingModel(
                chunk_id=CHUNK_A_ID,
                embedding_model=DATABASE_EMBEDDING_MODEL_ID,
                embedding=list(VECTOR_A),
            ),
            DocumentChunkEmbeddingModel(
                chunk_id=CHUNK_A_ID,
                embedding_model="synthetic-future-model-v2",
                embedding=list(VECTOR_B),
            ),
        ]
    )
    migrated_session.flush()

    models = migrated_session.scalars(
        select(DocumentChunkEmbeddingModel.embedding_model).order_by(
            DocumentChunkEmbeddingModel.embedding_model
        )
    ).all()
    assert models == [
        "fake-deterministic-v1",
        "synthetic-future-model-v2",
    ]


def test_repository_translates_duplicate_and_preserves_session_recovery(
    migrated_session: Session,
) -> None:
    _insert_chunks(migrated_session, CHUNK_A_ID, CHUNK_B_ID)
    repository = PostgresEmbeddingRepository(migrated_session, PROFILE)
    repository.insert(CHUNK_A_ID, VECTOR_A)

    with pytest.raises(EmbeddingPersistenceError) as captured:
        repository.insert(CHUNK_A_ID, VECTOR_B)

    assert str(captured.value) == PERSISTENCE_ERROR
    assert captured.value.__cause__ is None
    repository.insert(CHUNK_B_ID, VECTOR_B)
    assert _embedding_count(migrated_session) == 2


def test_repository_translates_missing_chunk_and_preserves_session_recovery(
    migrated_session: Session,
) -> None:
    _insert_chunks(migrated_session, CHUNK_A_ID)
    repository = PostgresEmbeddingRepository(migrated_session, PROFILE)

    with pytest.raises(EmbeddingPersistenceError) as captured:
        repository.insert(MISSING_CHUNK_ID, VECTOR_A)

    assert str(captured.value) == PERSISTENCE_ERROR
    assert captured.value.__cause__ is None
    repository.insert(CHUNK_A_ID, VECTOR_A)
    assert _embedding_count(migrated_session) == 1


@pytest.mark.parametrize(
    "profile",
    [
        EmbeddingProfile(model_id="wrong-model-v1", dimension=8),
        EmbeddingProfile(model_id="fake-deterministic-v1", dimension=7),
    ],
)
def test_repository_rejects_non_database_profile_before_sql(
    profile: EmbeddingProfile,
) -> None:
    with pytest.raises(EmbeddingPersistenceError) as captured:
        PostgresEmbeddingRepository(Session(), profile)

    assert str(captured.value) == PERSISTENCE_ERROR


@pytest.mark.parametrize(
    ("chunk_id", "embedding"),
    [
        ("94000000-0000-0000-0000-000000000003", VECTOR_A),
        (CHUNK_A_ID, list(VECTOR_A)),
        (CHUNK_A_ID, VECTOR_A[:-1]),
        (CHUNK_A_ID, (0.0,) * 8),
        (CHUNK_A_ID, (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, float("nan"))),
        (CHUNK_A_ID, (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, float("inf"))),
        (CHUNK_A_ID, (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1)),
    ],
)
def test_repository_rejects_invalid_identity_or_vector_before_sql(
    chunk_id: object,
    embedding: object,
) -> None:
    repository = PostgresEmbeddingRepository(Session(), PROFILE)

    with pytest.raises(EmbeddingPersistenceError) as captured:
        repository.insert(
            cast(UUID, chunk_id),
            cast(tuple[float, ...], embedding),
        )

    assert str(captured.value) == PERSISTENCE_ERROR


@pytest.mark.parametrize(
    ("embedding_model", "embedding"),
    [
        (" ", VECTOR_A),
        ("synthetic-zero-model", (0.0,) * 8),
    ],
)
def test_database_rejects_blank_model_and_zero_vector(
    migrated_session: Session,
    embedding_model: str,
    embedding: tuple[float, ...],
) -> None:
    _insert_chunks(migrated_session, CHUNK_A_ID)

    with pytest.raises(IntegrityError), migrated_session.begin_nested():
        migrated_session.add(
            DocumentChunkEmbeddingModel(
                chunk_id=CHUNK_A_ID,
                embedding_model=embedding_model,
                embedding=list(embedding),
            )
        )
        migrated_session.flush()

    assert _embedding_count(migrated_session) == 0
