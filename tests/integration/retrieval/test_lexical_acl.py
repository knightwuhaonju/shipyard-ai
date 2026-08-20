"""Primary PostgreSQL lexical retrieval behavior and SQL-path coverage."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from infra.postgres import (
    DomainRepository,
    PostgresDocumentRepository,
    PostgresLexicalSearchAdapter,
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
from services.retrieval import LexicalRetriever

_BASE_UPDATED_AT = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _id(namespace: int, value: int) -> UUID:
    return UUID(int=(0xA2 << 120) | (namespace << 112) | value)


@dataclass(frozen=True, slots=True)
class _ChunkSpec:
    key: int
    text: str
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
        for spec in specs:
            document_id = _id(1, spec.key)
            version_id = _id(2, spec.key)
            document_repository.insert_document(
                Document(
                    document_id=document_id,
                    source_system="synthetic-plm",
                    source_id=f"document-{spec.key}",
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
                        f"document-{spec.key}.{spec.document_type.value}"
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
            chunks.append(chunk)

        session.commit()
    return tuple(chunks)


def _persist_two_project_fixture(
    engine: Engine, allowed_project: UUID, denied_project: UUID
) -> tuple[DocumentChunk, DocumentChunk]:
    allowed_chunk, denied_chunk = _persist_records(
        engine,
        _ChunkSpec(
            key=1,
            text="ballast pump maintenance for the authorized project",
            security_level=SecurityLevel.INTERNAL,
            project_id=allowed_project,
        ),
        _ChunkSpec(
            key=2,
            text="ballast pump maintenance for the denied project",
            security_level=SecurityLevel.INTERNAL,
            project_id=denied_project,
        ),
    )
    return allowed_chunk, denied_chunk


def _retrieve(
    engine: Engine,
    query: str,
    scope: AuthorizationScope | None = None,
    filters: KnowledgeFilters | None = None,
    *,
    limit: int = 10,
) -> list[KnowledgeEvidence]:
    return LexicalRetriever(PostgresLexicalSearchAdapter(engine)).retrieve(
        query,
        scope if scope is not None else AuthorizationScope(),
        filters if filters is not None else KnowledgeFilters(),
        limit,
    )


def test_lexical_search_returns_only_the_authorized_project(
    migrated_engine: Engine,
) -> None:
    allowed_project = UUID("a2000000-0000-0000-0000-000000000001")
    denied_project = UUID("a2000000-0000-0000-0000-000000000002")
    allowed_chunk, denied_chunk = _persist_two_project_fixture(
        migrated_engine, allowed_project, denied_project
    )
    scope = AuthorizationScope(
        allowed_project_ids={str(allowed_project)},
        security_level=SecurityLevel.INTERNAL,
    )

    result = _retrieve(migrated_engine, "ballast pump", scope)

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}
    assert all(type(item) is KnowledgeEvidence for item in result)


@pytest.mark.parametrize(
    ("query", "stored_text"),
    [
        ("pump maintenance", "English pump maintenance procedure"),
        ("P-101-A", "Equipment identifier P-101-A requires inspection"),
        ("压载泵", "压载泵维护规程"),
    ],
)
def test_lexical_search_supports_english_identifiers_and_chinese_literals(
    migrated_engine: Engine, query: str, stored_text: str
) -> None:
    (matching_chunk,) = _persist_records(
        migrated_engine, _ChunkSpec(key=10, text=stored_text)
    )

    result = _retrieve(migrated_engine, query)

    assert [item.chunk_id for item in result] == [matching_chunk.chunk_id]


@pytest.mark.parametrize(
    ("query", "literal_text", "nonliteral_text"),
    [
        ("%", "pressure is 80% of the synthetic limit", "pressure is nominal"),
        ("_", "equipment code P_101 is literal", "equipment code P-101 differs"),
        ("\\", "folder\\manual contains a separator", "folder/manual differs"),
    ],
)
def test_lexical_search_treats_ilike_wildcards_as_literals(
    migrated_engine: Engine,
    query: str,
    literal_text: str,
    nonliteral_text: str,
) -> None:
    literal_chunk, nonliteral_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(key=20, text=literal_text),
        _ChunkSpec(key=21, text=nonliteral_text),
    )

    result = _retrieve(migrated_engine, query)

    assert [item.chunk_id for item in result] == [literal_chunk.chunk_id]
    assert nonliteral_chunk.chunk_id not in {item.chunk_id for item in result}


def test_lexical_search_applies_document_type_filter(
    migrated_engine: Engine,
) -> None:
    pdf_chunk, docx_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(key=30, text="ballast filter procedure"),
        _ChunkSpec(
            key=31,
            text="ballast filter procedure",
            document_type=DocumentType.DOCX,
        ),
    )

    pdf_result = _retrieve(
        migrated_engine,
        "ballast filter",
        filters=KnowledgeFilters(document_type=DocumentType.PDF),
    )
    docx_result = _retrieve(
        migrated_engine,
        "ballast filter",
        filters=KnowledgeFilters(document_type=DocumentType.DOCX),
    )

    assert [item.chunk_id for item in pdf_result] == [pdf_chunk.chunk_id]
    assert [item.chunk_id for item in docx_result] == [docx_chunk.chunk_id]


@pytest.mark.parametrize("dimension", ["ship", "project"])
@pytest.mark.parametrize("authorized", [True, False])
def test_lexical_search_intersects_ship_and_project_filters_with_scope(
    migrated_engine: Engine, dimension: str, authorized: bool
) -> None:
    resource_id = _id(3, 1 if dimension == "ship" else 2)
    other_id = _id(3, 11 if dimension == "ship" else 12)
    spec = _ChunkSpec(
        key=40,
        text="scoped ballast maintenance",
        ship_id=resource_id if dimension == "ship" else None,
        project_id=resource_id if dimension == "project" else None,
    )
    (chunk,) = _persist_records(migrated_engine, spec)
    allowed_id = resource_id if authorized else other_id
    scope = AuthorizationScope(
        allowed_ship_ids={str(allowed_id)} if dimension == "ship" else set(),
        allowed_project_ids=(
            {str(allowed_id)} if dimension == "project" else set()
        ),
    )
    filters = KnowledgeFilters(
        ship_id=resource_id if dimension == "ship" else None,
        project_id=resource_id if dimension == "project" else None,
    )

    result = _retrieve(migrated_engine, "ballast maintenance", scope, filters)

    assert [item.chunk_id for item in result] == (
        [chunk.chunk_id] if authorized else []
    )


def test_lexical_limit_returns_the_highest_ranked_result(
    migrated_engine: Engine,
) -> None:
    exact_chunk, weaker_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(key=50, text="ballast pump"),
        _ChunkSpec(
            key=51,
            text=(
                "A long synthetic maintenance paragraph with one ballast pump "
                "reference among unrelated valve coating welding schedule text."
            ),
        ),
    )

    result = _retrieve(migrated_engine, "ballast pump", limit=1)

    assert [item.chunk_id for item in result] == [exact_chunk.chunk_id]
    assert weaker_chunk.chunk_id not in {item.chunk_id for item in result}


def test_equal_scores_order_by_newer_source_then_ascending_chunk_uuid(
    migrated_engine: Engine,
) -> None:
    older_time = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    newer_time = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    older, newer_a, newer_b = _persist_records(
        migrated_engine,
        _ChunkSpec(key=60, text="identical ballast term", source_updated_at=older_time),
        _ChunkSpec(key=61, text="identical ballast term", source_updated_at=newer_time),
        _ChunkSpec(key=62, text="identical ballast term", source_updated_at=newer_time),
    )
    expected_newer = sorted([newer_a.chunk_id, newer_b.chunk_id])

    result = _retrieve(migrated_engine, "identical ballast term")

    assert [item.chunk_id for item in result] == [*expected_newer, older.chunk_id]


def test_lexical_search_returns_exact_evidence_fields_and_scores(
    migrated_engine: Engine,
) -> None:
    text = "Synthetic ballast pump maintenance evidence."
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=70,
            text=text,
            title="Synthetic Pump Manual",
            page=12,
            section="Maintenance / 2",
        ),
    )

    (evidence,) = _retrieve(migrated_engine, "ballast pump")

    assert evidence.document_id == _id(1, 70)
    assert evidence.version_id == _id(2, 70)
    assert evidence.chunk_id == chunk.chunk_id
    assert evidence.title == "Synthetic Pump Manual"
    assert evidence.section == "Maintenance / 2"
    assert evidence.page == 12
    assert evidence.source_uri == "s3://synthetic-documents/document-70.pdf"
    assert evidence.excerpt == text
    assert evidence.retrieval_score == evidence.lexical_score
    assert evidence.lexical_score is not None
    assert isfinite(evidence.lexical_score)
    assert evidence.lexical_score >= 0.0
    assert evidence.vector_score is None
    assert evidence.rerank_score is None


def test_long_evidence_excerpt_is_a_centered_two_thousand_character_window(
    migrated_engine: Engine,
) -> None:
    text = "a" * 2500 + "NEEDLE" + "b" * 1494
    _persist_records(migrated_engine, _ChunkSpec(key=80, text=text))

    (evidence,) = _retrieve(migrated_engine, "NEEDLE")

    assert len(text) == 4000
    assert len(evidence.excerpt) == 2000
    assert evidence.excerpt == text[1503:3503]
    assert "NEEDLE" in evidence.excerpt


def test_candidate_sql_contains_acl_limit_read_only_and_local_timeout(
    migrated_engine: Engine,
) -> None:
    allowed_project = UUID("a2000000-0000-0000-0000-000000000001")
    denied_project = UUID("a2000000-0000-0000-0000-000000000002")
    allowed_chunk, denied_chunk = _persist_two_project_fixture(
        migrated_engine, allowed_project, denied_project
    )
    scope = AuthorizationScope(
        allowed_project_ids={str(allowed_project)},
        security_level=SecurityLevel.INTERNAL,
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
        result = _retrieve(migrated_engine, "ballast pump", scope)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}
    normalized = [(" ".join(sql.lower().split()), params) for sql, params in executed]
    assert any(sql == "set transaction read only" for sql, _ in normalized)
    timeout_calls = [item for item in normalized if "set_config" in item[0]]
    assert len(timeout_calls) == 1
    assert "statement_timeout" in str(timeout_calls[0][1])
    assert "2000" in str(timeout_calls[0][1])

    candidate_sql = [
        sql
        for sql, _ in normalized
        if sql.startswith("select ") and "document_chunks" in sql
    ]
    assert len(candidate_sql) == 1
    sql = candidate_sql[0]
    where_position = sql.index(" where ")
    order_position = sql.index(" order by ")
    limit_position = sql.rindex(" limit ")
    for acl_column in ("security_level", "department", "ship_id", "project_id"):
        assert where_position < sql.index(acl_column, where_position) < order_position
    assert order_position < limit_position
