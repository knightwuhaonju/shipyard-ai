"""PostgreSQL vector retrieval is bounded, read-only, and ACL-filtered."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite, sqrt
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from adapters.embedding import FakeEmbeddingAdapter
from infra.postgres import (
    DocumentChunkEmbeddingModel,
    DomainRepository,
    PostgresDocumentRepository,
    PostgresEmbeddingRepository,
    PostgresVectorSearchAdapter,
)
from packages.common import DocumentType, SecurityLevel
from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters
from packages.domain import (
    Document,
    DocumentChunk,
    DocumentVersion,
    Ship,
    document_chunk_id,
)
from services.model_gateway import EmbeddingGateway, EmbeddingProfile
from services.retrieval import VectorRetrievalError, VectorRetriever

_BASE_UPDATED_AT = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
_MODEL_ID = "fake-deterministic-v1"
_PROFILE = EmbeddingProfile(model_id=_MODEL_ID, dimension=8)
_QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _id(namespace: int, value: int) -> UUID:
    return UUID(int=(0xB2 << 120) | (namespace << 112) | value)


@dataclass(frozen=True, slots=True)
class _ChunkSpec:
    key: int
    text: str
    embedding: tuple[float, ...] = _QUERY_VECTOR
    embedding_model: str = _MODEL_ID
    title: str = "Synthetic ballast rule"
    document_type: DocumentType = DocumentType.PDF
    source_updated_at: datetime = _BASE_UPDATED_AT
    security_level: SecurityLevel = SecurityLevel.PUBLIC
    ship_id: UUID | None = None
    project_id: UUID | None = None
    department: str | None = None
    page: int | None = 7
    section: str | None = "4.2"


def _persist_records(
    engine: Engine, *specs: _ChunkSpec
) -> tuple[DocumentChunk, ...]:
    chunks: list[DocumentChunk] = []
    with Session(engine) as session:
        domain_repository = DomainRepository(session)
        for ship_id in sorted(
            {spec.ship_id for spec in specs if spec.ship_id is not None}, key=str
        ):
            domain_repository.insert(
                Ship(
                    id=ship_id,
                    source_system="synthetic-mes",
                    source_id=f"ship-{ship_id}",
                    source_updated_at=_BASE_UPDATED_AT,
                    ship_code=f"SYN-{str(ship_id)[-6:]}",
                )
            )

        document_repository = PostgresDocumentRepository(session)
        embedding_repository = PostgresEmbeddingRepository(session, _PROFILE)
        for spec in specs:
            document_id = _id(1, spec.key)
            version_id = _id(2, spec.key)
            document_repository.insert_document(
                Document(
                    document_id=document_id,
                    source_system="synthetic-plm",
                    source_id=f"vector-document-{spec.key}",
                    title=spec.title,
                )
            )
            document_repository.insert_version(
                DocumentVersion(
                    version_id=version_id,
                    document_id=document_id,
                    checksum=f"{spec.key:064x}",
                    source_uri=(
                        "s3://synthetic-documents/"
                        f"vector-document-{spec.key}.{spec.document_type.value}"
                    ),
                    document_type=spec.document_type,
                    source_updated_at=spec.source_updated_at,
                    security_level=spec.security_level,
                    ship_id=spec.ship_id,
                    project_id=spec.project_id,
                    department=spec.department,
                )
            )
            chunk = DocumentChunk(
                chunk_id=document_chunk_id(version_id, ("Synthetic",), 0),
                version_id=version_id,
                structural_path=("Synthetic",),
                ordinal=0,
                normalized_text=spec.text,
                page=spec.page,
                section=spec.section,
            )
            document_repository.insert_chunks((chunk,))
            if spec.embedding_model == _MODEL_ID:
                embedding_repository.insert(chunk.chunk_id, spec.embedding)
            else:
                session.add(
                    DocumentChunkEmbeddingModel(
                        chunk_id=chunk.chunk_id,
                        embedding_model=spec.embedding_model,
                        embedding=list(spec.embedding),
                    )
                )
                session.flush()
            chunks.append(chunk)

        session.commit()
    return tuple(chunks)


def _persist_two_project_vector_fixture(
    engine: Engine,
    *,
    allowed_project: UUID,
    denied_project: UUID,
    embedding: tuple[float, ...],
) -> tuple[DocumentChunk, DocumentChunk]:
    allowed_chunk, denied_chunk = _persist_records(
        engine,
        _ChunkSpec(
            key=1,
            text="ballast pump maintenance for the authorized project",
            embedding=embedding,
            security_level=SecurityLevel.INTERNAL,
            project_id=allowed_project,
        ),
        _ChunkSpec(
            key=2,
            text="ballast pump maintenance for the denied project",
            embedding=embedding,
            security_level=SecurityLevel.INTERNAL,
            project_id=denied_project,
        ),
    )
    return allowed_chunk, denied_chunk


def _project_scope(project_id: UUID) -> AuthorizationScope:
    return AuthorizationScope(
        allowed_project_ids={str(project_id)},
        security_level=SecurityLevel.INTERNAL,
    )


def _retrieve(
    engine: Engine,
    *,
    query: str = "ballast pump",
    query_vector: tuple[float, ...] = _QUERY_VECTOR,
    scope: AuthorizationScope | None = None,
    filters: KnowledgeFilters | None = None,
    limit: int = 10,
) -> list[KnowledgeEvidence]:
    fake = FakeEmbeddingAdapter(_PROFILE, {query: query_vector})
    return VectorRetriever(
        EmbeddingGateway(fake),
        PostgresVectorSearchAdapter(engine, _PROFILE),
    ).retrieve(
        query,
        scope if scope is not None else AuthorizationScope(),
        filters if filters is not None else KnowledgeFilters(),
        limit,
    )


def _document_row_counts(engine: Engine) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        row = connection.execute(
            sql_text(
                "SELECT "
                "(SELECT count(*) FROM documents), "
                "(SELECT count(*) FROM document_versions), "
                "(SELECT count(*) FROM document_chunks), "
                "(SELECT count(*) FROM document_chunk_embeddings)"
            )
        ).one()
    return cast(tuple[int, int, int, int], tuple(row))


def _assert_all_tables_queryable(engine: Engine) -> None:
    table_names = inspect(engine).get_table_names()
    assert {
        "documents",
        "document_versions",
        "document_chunks",
        "document_chunk_embeddings",
    }.issubset(table_names)
    with engine.connect() as connection:
        quote = connection.dialect.identifier_preparer.quote
        for table_name in table_names:
            connection.execute(
                sql_text(f"SELECT count(*) FROM {quote(table_name)}")
            ).scalar_one()


def test_vector_search_returns_only_the_authorized_project(
    migrated_engine: Engine,
) -> None:
    allowed_project = UUID("b2000000-0000-0000-0000-000000000001")
    denied_project = UUID("b2000000-0000-0000-0000-000000000002")
    allowed_chunk, denied_chunk = _persist_two_project_vector_fixture(
        migrated_engine,
        allowed_project=allowed_project,
        denied_project=denied_project,
        embedding=_QUERY_VECTOR,
    )

    result = _retrieve(
        migrated_engine,
        query="ballast pump",
        query_vector=_QUERY_VECTOR,
        scope=_project_scope(allowed_project),
    )

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}
    assert result[0].vector_score == result[0].retrieval_score


def test_vector_search_isolates_the_exact_embedding_model(
    migrated_engine: Engine,
) -> None:
    matching_chunk, wrong_model_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=3,
            text="matching model semantic evidence",
            embedding=(0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ),
        _ChunkSpec(
            key=4,
            text="wrong model semantic evidence",
            embedding_model="other-model-v1",
        ),
    )

    result = _retrieve(migrated_engine, query="semantic model isolation")

    assert [item.chunk_id for item in result] == [matching_chunk.chunk_id]
    assert wrong_model_chunk.chunk_id not in {item.chunk_id for item in result}


@pytest.mark.parametrize(
    ("dimension", "spec", "scope"),
    [
        pytest.param(
            "security",
            _ChunkSpec(
                key=10,
                text="single dimension vector authorization",
                security_level=SecurityLevel.CONFIDENTIAL,
            ),
            AuthorizationScope(security_level=SecurityLevel.INTERNAL),
            id="security-clearance",
        ),
        pytest.param(
            "department",
            _ChunkSpec(
                key=10,
                text="single dimension vector authorization",
                department="quality",
            ),
            AuthorizationScope(departments={"engineering"}),
            id="department-membership",
        ),
        pytest.param(
            "ship",
            _ChunkSpec(
                key=10,
                text="single dimension vector authorization",
                ship_id=UUID("b2000000-0000-0000-0000-000000000102"),
            ),
            AuthorizationScope(
                allowed_ship_ids={"b2000000-0000-0000-0000-000000000101"}
            ),
            id="ship-membership",
        ),
        pytest.param(
            "project",
            _ChunkSpec(
                key=10,
                text="single dimension vector authorization",
                project_id=UUID("b2000000-0000-0000-0000-000000000202"),
            ),
            AuthorizationScope(
                allowed_project_ids={"b2000000-0000-0000-0000-000000000201"}
            ),
            id="project-membership",
        ),
    ],
)
def test_each_acl_dimension_denies_a_nonmatching_vector_candidate(
    migrated_engine: Engine,
    dimension: str,
    spec: _ChunkSpec,
    scope: AuthorizationScope,
) -> None:
    allowed_chunk, denied_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(key=9, text="equally similar public global evidence"),
        spec,
    )

    result = _retrieve(migrated_engine, scope=scope, limit=1)

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id], dimension
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}


@pytest.mark.parametrize("mismatched_dimension", ["department", "ship", "project"])
def test_department_ship_and_project_acl_dimensions_intersect(
    migrated_engine: Engine,
    mismatched_dimension: str,
) -> None:
    ship_id = UUID("b2000000-0000-0000-0000-000000000301")
    project_id = UUID("b2000000-0000-0000-0000-000000000302")
    _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=11,
            text="four dimension vector authorization",
            security_level=SecurityLevel.INTERNAL,
            department="quality",
            ship_id=ship_id,
            project_id=project_id,
        ),
    )
    scope = AuthorizationScope(
        security_level=SecurityLevel.INTERNAL,
        departments={
            "engineering" if mismatched_dimension == "department" else "quality"
        },
        allowed_ship_ids={
            str(_id(3, 11) if mismatched_dimension == "ship" else ship_id)
        },
        allowed_project_ids={
            str(_id(3, 12) if mismatched_dimension == "project" else project_id)
        },
    )

    assert _retrieve(migrated_engine, scope=scope) == []


def test_null_global_documents_are_visible_but_scoped_documents_fail_closed(
    migrated_engine: Engine,
) -> None:
    global_chunk, *_scoped = _persist_records(
        migrated_engine,
        _ChunkSpec(key=20, text="public global semantic evidence"),
        _ChunkSpec(
            key=21,
            text="internal semantic evidence",
            security_level=SecurityLevel.INTERNAL,
        ),
        _ChunkSpec(
            key=22,
            text="department semantic evidence",
            department="engineering",
        ),
        _ChunkSpec(
            key=23,
            text="ship semantic evidence",
            ship_id=_id(3, 23),
        ),
        _ChunkSpec(
            key=24,
            text="project semantic evidence",
            project_id=_id(3, 24),
        ),
    )

    result = _retrieve(migrated_engine, query="semantic default scope")

    assert [item.chunk_id for item in result] == [global_chunk.chunk_id]


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_scope_uuid_canonicalization_accepts_uppercase_without_malformed_bypass(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    allowed_id = _id(3, 25 if dimension == "ship" else 26)
    denied_id = _id(3, 27 if dimension == "ship" else 28)
    allowed_chunk, denied_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=25,
            text="uppercase canonical scope evidence",
            ship_id=allowed_id if dimension == "ship" else None,
            project_id=allowed_id if dimension == "project" else None,
        ),
        _ChunkSpec(
            key=26,
            text="malformed scope must not grant evidence",
            ship_id=denied_id if dimension == "ship" else None,
            project_id=denied_id if dimension == "project" else None,
        ),
    )
    mixed_scope_values = {
        str(allowed_id).upper(),
        "not-a-uuid",
        f"{{{denied_id}}}",
        "1",
    }
    scope = AuthorizationScope(
        allowed_ship_ids=mixed_scope_values if dimension == "ship" else set(),
        allowed_project_ids=(
            mixed_scope_values if dimension == "project" else set()
        ),
    )

    result = _retrieve(migrated_engine, scope=scope)

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}


def test_vector_search_applies_document_type_filter(
    migrated_engine: Engine,
) -> None:
    pdf_chunk, docx_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(key=30, text="pdf vector filter"),
        _ChunkSpec(
            key=31,
            text="docx vector filter",
            document_type=DocumentType.DOCX,
        ),
    )

    pdf_result = _retrieve(
        migrated_engine,
        filters=KnowledgeFilters(document_type=DocumentType.PDF),
    )
    docx_result = _retrieve(
        migrated_engine,
        filters=KnowledgeFilters(document_type=DocumentType.DOCX),
    )

    assert [item.chunk_id for item in pdf_result] == [pdf_chunk.chunk_id]
    assert [item.chunk_id for item in docx_result] == [docx_chunk.chunk_id]


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_ship_and_project_filters_only_narrow_the_authorized_scope(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    resource_id = _id(3, 40 if dimension == "ship" else 41)
    other_id = _id(3, 50 if dimension == "ship" else 51)
    selected_chunk, rejected_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=40,
            text="selected scoped vector filter evidence",
            ship_id=resource_id if dimension == "ship" else None,
            project_id=resource_id if dimension == "project" else None,
        ),
        _ChunkSpec(
            key=42,
            text="rejected but authorized vector filter evidence",
            ship_id=other_id if dimension == "ship" else None,
            project_id=other_id if dimension == "project" else None,
        ),
    )
    scope = AuthorizationScope(
        allowed_ship_ids=(
            {str(resource_id), str(other_id)} if dimension == "ship" else set()
        ),
        allowed_project_ids=(
            {str(resource_id), str(other_id)}
            if dimension == "project"
            else set()
        ),
    )
    filters = KnowledgeFilters(
        ship_id=resource_id if dimension == "ship" else None,
        project_id=resource_id if dimension == "project" else None,
    )
    executed: list[tuple[str, object]] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append((statement, parameters))

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        result = _retrieve(migrated_engine, scope=scope, filters=filters)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert [item.chunk_id for item in result] == [selected_chunk.chunk_id]
    assert rejected_chunk.chunk_id not in {item.chunk_id for item in result}
    candidate_calls = [
        (statement, parameters)
        for statement, parameters in executed
        if statement.lstrip().lower().startswith("select ")
        and "document_chunk_embeddings" in statement.lower()
    ]
    assert len(candidate_calls) == 1
    candidate_sql, candidate_parameters = candidate_calls[0]
    filter_parameter = f"{dimension}_id"
    assert f"%({filter_parameter})s" in candidate_sql
    assert isinstance(candidate_parameters, dict)
    assert candidate_parameters[filter_parameter] == resource_id


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_out_of_scope_filter_returns_zero_without_vector_fallback(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    resource_id = _id(3, 60)
    other_id = _id(3, 61)
    _filtered_chunk, fallback_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=41,
            text="out of scope vector filter",
            ship_id=resource_id if dimension == "ship" else None,
            project_id=resource_id if dimension == "project" else None,
        ),
        _ChunkSpec(
            key=43,
            text="authorized candidate must not be returned by fallback",
            ship_id=other_id if dimension == "ship" else None,
            project_id=other_id if dimension == "project" else None,
        ),
    )
    scope = AuthorizationScope(
        allowed_ship_ids={str(other_id)} if dimension == "ship" else set(),
        allowed_project_ids={str(other_id)} if dimension == "project" else set(),
    )
    filters = KnowledgeFilters(
        ship_id=resource_id if dimension == "ship" else None,
        project_id=resource_id if dimension == "project" else None,
    )
    assert [
        item.chunk_id for item in _retrieve(migrated_engine, scope=scope)
    ] == [fallback_chunk.chunk_id]
    executed: list[tuple[str, object]] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append((statement, parameters))

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        result = _retrieve(migrated_engine, scope=scope, filters=filters)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    candidate_calls = [
        (statement, parameters)
        for statement, parameters in executed
        if statement.lstrip().lower().startswith("select ")
        and "document_chunk_embeddings" in statement.lower()
    ]
    assert result == []
    assert len(candidate_calls) == 1
    candidate_sql, candidate_parameters = candidate_calls[0]
    filter_parameter = f"{dimension}_id"
    assert f"%({filter_parameter})s" in candidate_sql
    assert isinstance(candidate_parameters, dict)
    assert candidate_parameters[filter_parameter] == resource_id


def test_vector_limit_returns_only_the_nearest_candidate(
    migrated_engine: Engine,
) -> None:
    nearest, farther = _persist_records(
        migrated_engine,
        _ChunkSpec(key=50, text="nearest vector evidence"),
        _ChunkSpec(
            key=51,
            text="farther vector evidence",
            embedding=(0.6, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ),
    )

    result = _retrieve(migrated_engine, limit=1)

    assert [item.chunk_id for item in result] == [nearest.chunk_id]
    assert farther.chunk_id not in {item.chunk_id for item in result}


@pytest.mark.parametrize(
    ("embedding", "expected_score"),
    [
        ((2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2.0 / sqrt(5.0)),
        ((-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0),
    ],
)
def test_vector_score_matches_an_independent_cosine_oracle_and_clamps_at_zero(
    migrated_engine: Engine,
    embedding: tuple[float, ...],
    expected_score: float,
) -> None:
    _persist_records(
        migrated_engine,
        _ChunkSpec(key=55, text="independent cosine score", embedding=embedding),
    )

    (evidence,) = _retrieve(migrated_engine)

    assert evidence.vector_score == pytest.approx(expected_score, rel=1e-6)
    assert evidence.retrieval_score == pytest.approx(expected_score, rel=1e-6)


def test_equal_distances_order_by_newer_source_then_ascending_chunk_uuid(
    migrated_engine: Engine,
) -> None:
    older_time = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    newer_time = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    older, newer_a, newer_b = _persist_records(
        migrated_engine,
        _ChunkSpec(key=60, text="older tied vector", source_updated_at=older_time),
        _ChunkSpec(key=61, text="newer tied vector a", source_updated_at=newer_time),
        _ChunkSpec(key=62, text="newer tied vector b", source_updated_at=newer_time),
    )
    expected_newer = sorted([newer_a.chunk_id, newer_b.chunk_id])

    result = _retrieve(migrated_engine)

    assert [item.chunk_id for item in result] == [*expected_newer, older.chunk_id]


def test_vector_search_returns_exact_existing_evidence_contract(
    migrated_engine: Engine,
) -> None:
    text_value = "Synthetic ballast pump maintenance evidence."
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=70,
            text=text_value,
            title="Synthetic Vector Manual",
            page=12,
            section="Maintenance / 2",
        ),
    )

    (evidence,) = _retrieve(migrated_engine)

    assert type(evidence) is KnowledgeEvidence
    assert evidence.document_id == _id(1, 70)
    assert evidence.version_id == _id(2, 70)
    assert evidence.chunk_id == chunk.chunk_id
    assert evidence.title == "Synthetic Vector Manual"
    assert evidence.section == "Maintenance / 2"
    assert evidence.page == 12
    assert evidence.source_uri == "s3://synthetic-documents/vector-document-70.pdf"
    assert evidence.excerpt == text_value
    assert evidence.retrieval_score == evidence.vector_score
    assert evidence.vector_score is not None
    assert isfinite(evidence.vector_score)
    assert evidence.lexical_score is None
    assert evidence.rerank_score is None


def test_vector_excerpt_centers_a_literal_match_in_long_evidence(
    migrated_engine: Engine,
) -> None:
    text_value = "a" * 2500 + "NEEDLE" + "b" * 1494
    _persist_records(migrated_engine, _ChunkSpec(key=80, text=text_value))

    (evidence,) = _retrieve(migrated_engine, query="NEEDLE")

    assert len(evidence.excerpt) == 2000
    assert evidence.excerpt == text_value[1503:3503]
    assert "NEEDLE" in evidence.excerpt


def test_semantic_only_vector_excerpt_starts_at_the_beginning(
    migrated_engine: Engine,
) -> None:
    text_value = "semantic-only evidence " + "x" * 3977
    assert len(text_value) == 4000
    _persist_records(migrated_engine, _ChunkSpec(key=81, text=text_value))

    (evidence,) = _retrieve(migrated_engine, query="absent literal query")

    assert evidence.excerpt == text_value[:2000]


def test_candidate_sql_binds_profile_filters_acl_order_and_limit_before_ranking(
    migrated_engine: Engine,
) -> None:
    ship_id = _id(3, 90)
    project_id = _id(3, 91)
    query_sentinel = "query-bind-sentinel-9f4a"
    vector_sentinel = (
        0.125,
        -0.25,
        0.375,
        0.5,
        -0.625,
        0.75,
        -0.875,
        1.0,
    )
    database_vector_sentinel = (
        "[0.125,-0.25,0.375,0.5,-0.625,0.75,-0.875,1.0]"
    )
    department_sentinel = "department-bind-sentinel-7c91"
    security_sentinel = SecurityLevel.RESTRICTED
    document_type_sentinel = DocumentType.MARKDOWN
    limit_sentinel = 7
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=90,
            text="sql profile acl vector evidence",
            security_level=security_sentinel,
            department=department_sentinel,
            ship_id=ship_id,
            project_id=project_id,
            document_type=document_type_sentinel,
        ),
    )
    scope = AuthorizationScope(
        security_level=security_sentinel,
        departments={department_sentinel},
        allowed_ship_ids={str(ship_id)},
        allowed_project_ids={str(project_id)},
    )
    filters = KnowledgeFilters(
        document_type=document_type_sentinel,
        ship_id=ship_id,
        project_id=project_id,
    )
    executed: list[tuple[str, object]] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append((statement, parameters))

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        result = _retrieve(
            migrated_engine,
            query=query_sentinel,
            query_vector=vector_sentinel,
            scope=scope,
            filters=filters,
            limit=limit_sentinel,
        )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert [item.chunk_id for item in result] == [chunk.chunk_id]
    normalized = [(" ".join(sql.lower().split()), params) for sql, params in executed]
    assert sum(sql == "set transaction read only" for sql, _ in normalized) == 1
    assert sum(
        sql == "set local statement_timeout = 2000" for sql, _ in normalized
    ) == 1

    candidate_calls = [
        (sql, params)
        for sql, params in normalized
        if sql.startswith("select ") and "document_chunk_embeddings" in sql
    ]
    assert len(candidate_calls) == 1
    candidate_sql, candidate_parameters = candidate_calls[0]
    where_position = candidate_sql.index(" where ")
    order_position = candidate_sql.index(" order by ")
    limit_position = candidate_sql.rindex(" limit ")
    for constrained_column in (
        "embedding_model",
        "document_type",
        "security_level",
        "department",
        "ship_id",
        "project_id",
    ):
        assert (
            where_position
            < candidate_sql.index(constrained_column, where_position)
            < order_position
        )
    assert "<=>" in candidate_sql[:order_position]
    assert "distance asc" in candidate_sql[order_position:]
    assert "source_updated_at desc" in candidate_sql[order_position:]
    assert "chunk_id asc" in candidate_sql[order_position:]
    assert order_position < limit_position

    assert "%(query_embedding)s" in candidate_sql
    assert "%(embedding_model)s" in candidate_sql
    assert "%(scope_security_level)s" in candidate_sql
    assert "%(scope_departments_1)s" in candidate_sql
    assert "%(scope_ship_ids_1)s" in candidate_sql
    assert "%(scope_project_ids_1)s" in candidate_sql
    assert "%(document_type)s" in candidate_sql
    assert "%(ship_id)s" in candidate_sql
    assert "%(project_id)s" in candidate_sql
    assert "%(limit)s" in candidate_sql

    assert query_sentinel not in candidate_sql
    assert database_vector_sentinel not in candidate_sql
    assert _MODEL_ID not in candidate_sql
    assert department_sentinel not in candidate_sql
    assert document_type_sentinel.value not in candidate_sql
    assert str(ship_id) not in candidate_sql
    assert str(project_id) not in candidate_sql
    assert isinstance(candidate_parameters, dict)
    assert set(candidate_parameters) == {
        "query_embedding",
        "embedding_model",
        "scope_security_level",
        "scope_departments_1",
        "scope_ship_ids_1",
        "scope_project_ids_1",
        "document_type",
        "ship_id",
        "project_id",
        "limit",
    }
    assert "query" not in candidate_parameters
    assert query_sentinel not in candidate_parameters.values()
    assert candidate_parameters == {
        "query_embedding": database_vector_sentinel,
        "embedding_model": _MODEL_ID,
        "scope_security_level": security_sentinel.value,
        "scope_departments_1": department_sentinel,
        "scope_ship_ids_1": ship_id,
        "scope_project_ids_1": project_id,
        "document_type": document_type_sentinel.value,
        "ship_id": ship_id,
        "project_id": project_id,
        "limit": limit_sentinel,
    }


def test_malicious_query_model_and_document_text_remain_bound_untrusted_data(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malicious_text = "x'); DROP TABLE documents; --"
    malicious_profile = EmbeddingProfile(
        model_id=malicious_text,
        dimension=8,
    )
    vector_sentinel = (
        0.125,
        -0.25,
        0.375,
        0.5,
        -0.625,
        0.75,
        -0.875,
        1.0,
    )
    database_vector_sentinel = (
        "[0.125,-0.25,0.375,0.5,-0.625,0.75,-0.875,1.0]"
    )
    target_chunk, unrelated_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=92,
            text=f"Synthetic literal-bearing document: {malicious_text}",
            embedding=vector_sentinel,
            embedding_model=malicious_text,
        ),
        _ChunkSpec(
            key=93,
            text="unrelated default-model document",
            embedding=vector_sentinel,
        ),
    )
    monkeypatch.setattr(
        "infra.postgres.vector_retrieval.DATABASE_EMBEDDING_MODEL_ID",
        malicious_text,
    )
    fake = FakeEmbeddingAdapter(malicious_profile, {malicious_text: vector_sentinel})
    retriever = VectorRetriever(
        EmbeddingGateway(fake),
        PostgresVectorSearchAdapter(migrated_engine, malicious_profile),
    )
    before_counts = _document_row_counts(migrated_engine)
    executed: list[tuple[str, object]] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append((statement, parameters))

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        result = retriever.retrieve(
            malicious_text,
            AuthorizationScope(),
            KnowledgeFilters(),
            limit=1,
        )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert [item.chunk_id for item in result] == [target_chunk.chunk_id]
    assert unrelated_chunk.chunk_id not in {item.chunk_id for item in result}
    assert malicious_text in result[0].excerpt
    candidate_calls = [
        (statement, parameters)
        for statement, parameters in executed
        if statement.lstrip().lower().startswith("select ")
        and "document_chunk_embeddings" in statement.lower()
    ]
    assert len(candidate_calls) == 1
    candidate_sql, candidate_parameters = candidate_calls[0]
    assert malicious_text not in candidate_sql
    assert database_vector_sentinel not in candidate_sql
    assert isinstance(candidate_parameters, dict)
    assert candidate_parameters["embedding_model"] == malicious_text
    assert candidate_parameters["query_embedding"] == database_vector_sentinel
    assert "query" not in candidate_parameters

    forbidden_starts = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE ",
        "ALTER ",
        "DROP ",
        "TRUNCATE ",
        "COMMENT ",
        "GRANT ",
        "REVOKE ",
    )
    normalized_sql = [
        " ".join(statement.upper().split()) for statement, _ in executed
    ]
    assert all(
        not statement.startswith(forbidden_starts) for statement in normalized_sql
    )
    assert _document_row_counts(migrated_engine) == before_counts
    _assert_all_tables_queryable(migrated_engine)


def test_successful_vector_search_is_read_only_and_releases_its_connection(
    migrated_engine: Engine,
) -> None:
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(key=91, text="read only vector search evidence"),
    )
    before_counts = _document_row_counts(migrated_engine)
    pool = cast(Any, migrated_engine.pool)
    assert pool.checkedout() == 0
    executed: list[str] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append(" ".join(statement.upper().split()))

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        result = _retrieve(migrated_engine)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    forbidden_starts = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE ",
        "ALTER ",
        "DROP ",
        "TRUNCATE ",
        "COMMENT ",
        "GRANT ",
        "REVOKE ",
    )
    assert [item.chunk_id for item in result] == [chunk.chunk_id]
    assert all(not statement.startswith(forbidden_starts) for statement in executed)
    assert _document_row_counts(migrated_engine) == before_counts
    assert pool.checkedout() == 0


@pytest.mark.parametrize(
    "invalid_profile",
    [
        EmbeddingProfile(model_id="wrong-model-v1", dimension=8),
        EmbeddingProfile(model_id=_MODEL_ID, dimension=7),
    ],
)
def test_adapter_rejects_non_database_profile_before_sql(
    migrated_engine: Engine,
    invalid_profile: EmbeddingProfile,
) -> None:
    executed: list[str] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        with pytest.raises(
            VectorRetrievalError, match="^vector retrieval unavailable$"
        ) as captured:
            PostgresVectorSearchAdapter(migrated_engine, invalid_profile)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert executed == []
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("query_vector", "call_profile"),
    [
        ((1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), _PROFILE),
        (_QUERY_VECTOR, EmbeddingProfile(model_id="wrong-model-v1", dimension=8)),
        (_QUERY_VECTOR, EmbeddingProfile(model_id=_MODEL_ID, dimension=7)),
    ],
)
def test_adapter_rejects_dimension_or_call_profile_mismatch_before_sql(
    migrated_engine: Engine,
    query_vector: tuple[float, ...],
    call_profile: EmbeddingProfile,
) -> None:
    executed: list[str] = []

    def _capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        executed.append(statement)

    adapter = PostgresVectorSearchAdapter(migrated_engine, _PROFILE)
    event.listen(migrated_engine, "before_cursor_execute", _capture)
    try:
        with pytest.raises(
            VectorRetrievalError, match="^vector retrieval unavailable$"
        ) as captured:
            adapter.search(
                "secret dimension query",
                query_vector,
                call_profile,
                AuthorizationScope(),
                KnowledgeFilters(),
                10,
            )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert "secret dimension query" not in str(captured.value)
    assert executed == []
    assert captured.value.__cause__ is None


def test_unavailable_local_port_uses_fixed_cause_free_error_without_checkout(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_query = "secret unavailable query b27e"
    secret_vector = (0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28)
    secret_model = "secret-unavailable-model-b27e"
    secret_profile = EmbeddingProfile(model_id=secret_model, dimension=8)
    monkeypatch.setattr(
        "infra.postgres.vector_retrieval.DATABASE_EMBEDDING_MODEL_ID",
        secret_model,
    )

    # Keeping this TCP port bound but not listening makes it unavailable to both
    # a server and this client for the duration of the connection attempt.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved_socket:
        reserved_socket.bind(("127.0.0.1", 0))
        unavailable_port = cast(tuple[str, int], reserved_socket.getsockname())[1]
        unavailable_engine = create_engine(
            migrated_engine.url.set(host="127.0.0.1", port=unavailable_port),
            connect_args={"connect_timeout": 1},
        )
        assert unavailable_engine.url.database == "shipyard_ai_test"
        pool = cast(Any, unavailable_engine.pool)
        assert pool.checkedout() == 0
        adapter = PostgresVectorSearchAdapter(unavailable_engine, secret_profile)

        try:
            with pytest.raises(VectorRetrievalError) as captured:
                adapter.search(
                    secret_query,
                    secret_vector,
                    secret_profile,
                    AuthorizationScope(),
                    KnowledgeFilters(),
                    10,
                )
            assert pool.checkedout() == 0
        finally:
            unavailable_engine.dispose()

    assert type(captured.value) is VectorRetrievalError
    assert str(captured.value) == "vector retrieval unavailable"
    for secret in (
        secret_query,
        repr(secret_vector),
        secret_model,
        str(unavailable_port),
    ):
        assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None or captured.value.__suppress_context__


def test_database_failure_after_checkout_releases_connection_with_fixed_error(
    migrated_engine: Engine,
) -> None:
    secret_query = "secret database query a19f"
    secret_vector = (0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18)
    secret_driver_error = "secret driver failure a19f"
    pool = cast(Any, migrated_engine.pool)
    assert pool.checkedout() == 0
    checked_out_during_failure: list[int] = []
    candidate_attempts: list[str] = []

    def _fail_candidate_after_checkout(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: object,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if (
            statement.lstrip().lower().startswith("select ")
            and "document_chunk_embeddings" in statement.lower()
        ):
            candidate_attempts.append(statement)
            checked_out_during_failure.append(pool.checkedout())
            raise SQLAlchemyError(secret_driver_error)

    adapter = PostgresVectorSearchAdapter(migrated_engine, _PROFILE)
    event.listen(
        migrated_engine,
        "before_cursor_execute",
        _fail_candidate_after_checkout,
    )
    try:
        with pytest.raises(VectorRetrievalError) as captured:
            adapter.search(
                secret_query,
                secret_vector,
                _PROFILE,
                AuthorizationScope(),
                KnowledgeFilters(),
                10,
            )
    finally:
        event.remove(
            migrated_engine,
            "before_cursor_execute",
            _fail_candidate_after_checkout,
        )

    assert type(captured.value) is VectorRetrievalError
    assert str(captured.value) == "vector retrieval unavailable"
    for secret in (
        secret_query,
        repr(secret_vector),
        _MODEL_ID,
        secret_driver_error,
    ):
        assert secret not in str(captured.value)
    assert len(candidate_attempts) == 1
    assert checked_out_during_failure == [1]
    assert pool.checkedout() == 0
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None or captured.value.__suppress_context__


class _FakeRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _NonFiniteDistanceSession:
    def __init__(self, _engine: Engine) -> None:
        self._execute_count = 0

    def __enter__(self) -> _NonFiniteDistanceSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _NonFiniteDistanceSession:
        return self

    def execute(
        self, _statement: object, _parameters: object = None
    ) -> _FakeRows:
        self._execute_count += 1
        if self._execute_count < 3:
            return _FakeRows([])
        return _FakeRows(
            [
                SimpleNamespace(
                    document_id=_id(1, 99),
                    version_id=_id(2, 99),
                    chunk_id=_id(4, 99),
                    title="Synthetic nonfinite evidence",
                    section="1",
                    page=1,
                    source_uri="s3://synthetic/nonfinite.pdf",
                    normalized_text="Synthetic nonfinite evidence",
                    distance=float("nan"),
                )
            ]
        )


def test_nonfinite_cosine_distance_uses_the_fixed_vector_error(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "infra.postgres.vector_retrieval.Session", _NonFiniteDistanceSession
    )

    with pytest.raises(
        VectorRetrievalError, match="^vector retrieval unavailable$"
    ) as captured:
        PostgresVectorSearchAdapter(migrated_engine, _PROFILE).search(
            "nonfinite",
            _QUERY_VECTOR,
            _PROFILE,
            AuthorizationScope(),
            KnowledgeFilters(),
            10,
        )

    assert captured.value.__cause__ is None


class _ProgrammingFailureSession(_NonFiniteDistanceSession):
    def execute(
        self, _statement: object, _parameters: object = None
    ) -> _FakeRows:
        raise TypeError("adapter programming failure sentinel")


def test_adapter_does_not_translate_programming_errors(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "infra.postgres.vector_retrieval.Session", _ProgrammingFailureSession
    )

    with pytest.raises(TypeError, match="^adapter programming failure sentinel$"):
        PostgresVectorSearchAdapter(migrated_engine, _PROFILE).search(
            "programming failure",
            _QUERY_VECTOR,
            _PROFILE,
            AuthorizationScope(),
            KnowledgeFilters(),
            10,
        )
