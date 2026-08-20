"""Primary PostgreSQL lexical retrieval behavior and SQL-path coverage."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy import text as sql_text
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
from services.retrieval import LexicalRetrievalError, LexicalRetriever

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


def _document_row_counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        row = connection.execute(
            sql_text(
                "SELECT "
                "(SELECT count(*) FROM documents), "
                "(SELECT count(*) FROM document_versions), "
                "(SELECT count(*) FROM document_chunks)"
            )
        ).one()
    return cast(tuple[int, int, int], tuple(row))


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
    ("dimension", "spec", "scope"),
    [
        pytest.param(
            "security",
            _ChunkSpec(
                key=3,
                text="single dimension authorization matrix",
                security_level=SecurityLevel.CONFIDENTIAL,
            ),
            AuthorizationScope(security_level=SecurityLevel.INTERNAL),
            id="security-clearance",
        ),
        pytest.param(
            "department",
            _ChunkSpec(
                key=3,
                text="single dimension authorization matrix",
                department="quality",
            ),
            AuthorizationScope(departments={"engineering"}),
            id="department-membership",
        ),
        pytest.param(
            "ship",
            _ChunkSpec(
                key=3,
                text="single dimension authorization matrix",
                ship_id=UUID("a2000000-0000-0000-0000-000000000102"),
            ),
            AuthorizationScope(
                allowed_ship_ids={"a2000000-0000-0000-0000-000000000101"}
            ),
            id="ship-membership",
        ),
        pytest.param(
            "project",
            _ChunkSpec(
                key=3,
                text="single dimension authorization matrix",
                project_id=UUID("a2000000-0000-0000-0000-000000000202"),
            ),
            AuthorizationScope(
                allowed_project_ids={"a2000000-0000-0000-0000-000000000201"}
            ),
            id="project-membership",
        ),
    ],
)
def test_each_acl_dimension_independently_denies_a_nonmatching_chunk(
    migrated_engine: Engine,
    dimension: str,
    spec: _ChunkSpec,
    scope: AuthorizationScope,
) -> None:
    _persist_records(migrated_engine, spec)

    result = _retrieve(migrated_engine, "authorization matrix", scope)

    assert result == [], dimension


@pytest.mark.parametrize("mismatched_dimension", ["department", "ship", "project"])
def test_all_scoped_acl_dimensions_intersect_and_one_mismatch_denies(
    migrated_engine: Engine,
    mismatched_dimension: str,
) -> None:
    ship_id = UUID("a2000000-0000-0000-0000-000000000301")
    project_id = UUID("a2000000-0000-0000-0000-000000000302")
    _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=4,
            text="intersection authorization matrix",
            department="quality",
            ship_id=ship_id,
            project_id=project_id,
        ),
    )
    scope = AuthorizationScope(
        departments={
            "engineering" if mismatched_dimension == "department" else "quality"
        },
        allowed_ship_ids={
            str(
                UUID("a2000000-0000-0000-0000-000000000311")
                if mismatched_dimension == "ship"
                else ship_id
            )
        },
        allowed_project_ids={
            str(
                UUID("a2000000-0000-0000-0000-000000000312")
                if mismatched_dimension == "project"
                else project_id
            )
        },
    )

    result = _retrieve(migrated_engine, "authorization matrix", scope)

    assert result == []


def test_default_scope_retrieves_only_a_public_fully_global_document(
    migrated_engine: Engine,
) -> None:
    global_chunk, *_scoped_chunks = _persist_records(
        migrated_engine,
        _ChunkSpec(key=5, text="default scope authorization matrix"),
        _ChunkSpec(
            key=6,
            text="default scope authorization matrix",
            security_level=SecurityLevel.INTERNAL,
        ),
        _ChunkSpec(
            key=7,
            text="default scope authorization matrix",
            department="engineering",
        ),
        _ChunkSpec(
            key=8,
            text="default scope authorization matrix",
            ship_id=UUID("a2000000-0000-0000-0000-000000000401"),
        ),
        _ChunkSpec(
            key=9,
            text="default scope authorization matrix",
            project_id=UUID("a2000000-0000-0000-0000-000000000402"),
        ),
    )

    result = _retrieve(migrated_engine, "authorization matrix")

    assert [item.chunk_id for item in result] == [global_chunk.chunk_id]


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_invalid_scope_uuid_values_neither_raise_nor_grant_scoped_documents(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    allowed_id = UUID("a2000000-0000-0000-0000-000000000010")
    denied_id = UUID("a2000000-0000-0000-0000-000000000001")
    allowed_chunk, denied_chunk = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=13,
            text="malformed scope authorization matrix",
            ship_id=allowed_id if dimension == "ship" else None,
            project_id=allowed_id if dimension == "project" else None,
        ),
        _ChunkSpec(
            key=14,
            text="malformed scope authorization matrix",
            ship_id=denied_id if dimension == "ship" else None,
            project_id=denied_id if dimension == "project" else None,
        ),
    )
    scope_values = {
        str(allowed_id),
        "not-a-uuid",
        "{a2000000-0000-0000-0000-000000000001}",
        "1",
    }
    scope = AuthorizationScope(
        allowed_ship_ids=scope_values if dimension == "ship" else set(),
        allowed_project_ids=scope_values if dimension == "project" else set(),
    )

    result = _retrieve(migrated_engine, "authorization matrix", scope)

    assert [item.chunk_id for item in result] == [allowed_chunk.chunk_id]
    assert denied_chunk.chunk_id not in {item.chunk_id for item in result}


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_uppercase_canonical_scope_uuid_is_accepted(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    resource_id = UUID("a2000000-0000-0000-0000-0000000000ab")
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=15,
            text="uppercase canonical authorization matrix",
            ship_id=resource_id if dimension == "ship" else None,
            project_id=resource_id if dimension == "project" else None,
        ),
    )
    scope = AuthorizationScope(
        allowed_ship_ids={str(resource_id).upper()} if dimension == "ship" else set(),
        allowed_project_ids=(
            {str(resource_id).upper()} if dimension == "project" else set()
        ),
    )

    result = _retrieve(migrated_engine, "authorization matrix", scope)

    assert [item.chunk_id for item in result] == [chunk.chunk_id]


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_brace_wrapped_scope_uuid_is_denied(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    resource_id = UUID("a2000000-0000-0000-0000-000000000001")
    _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=16,
            text="brace wrapped authorization matrix",
            ship_id=resource_id if dimension == "ship" else None,
            project_id=resource_id if dimension == "project" else None,
        ),
    )
    wrapped_id = "{a2000000-0000-0000-0000-000000000001}"
    scope = AuthorizationScope(
        allowed_ship_ids={wrapped_id} if dimension == "ship" else set(),
        allowed_project_ids={wrapped_id} if dimension == "project" else set(),
    )

    result = _retrieve(migrated_engine, "authorization matrix", scope)

    assert result == []


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


@pytest.mark.parametrize("dimension", ["ship", "project"])
def test_out_of_scope_filter_returns_zero_without_an_unfiltered_fallback(
    migrated_engine: Engine,
    dimension: str,
) -> None:
    resource_id = UUID("a2000000-0000-0000-0000-000000000501")
    other_id = UUID("a2000000-0000-0000-0000-000000000502")
    _persist_records(
        migrated_engine,
        _ChunkSpec(
            key=41,
            text="out of scope filter authorization matrix",
            ship_id=resource_id if dimension == "ship" else None,
            project_id=resource_id if dimension == "project" else None,
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
        result = _retrieve(
            migrated_engine,
            "filter authorization matrix",
            scope,
            filters,
        )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    candidate_selects = [
        statement
        for statement in executed
        if statement.lstrip().lower().startswith("select ")
        and "document_chunks" in statement.lower()
    ]
    assert result == []
    assert len(candidate_selects) == 1


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


def test_lexical_score_matches_independent_component_oracle(
    migrated_engine: Engine,
) -> None:
    document_text = "Synthetic ballast pump maintenance evidence."
    query = "ballast pump"
    _persist_records(
        migrated_engine,
        _ChunkSpec(key=71, text=document_text, title="Synthetic score oracle"),
    )

    (evidence,) = _retrieve(migrated_engine, query)
    parameters = {"document_text": document_text, "query": query}
    with migrated_engine.connect() as connection:
        fts_normalized_32 = connection.scalar(
            sql_text(
                "SELECT ts_rank_cd("
                "to_tsvector('simple'::regconfig, :document_text), "
                "plainto_tsquery('simple'::regconfig, :query), 32)"
            ),
            parameters,
        )
        trigram = connection.scalar(
            sql_text("SELECT similarity(:document_text, :query)"), parameters
        )
        fts_unnormalized = connection.scalar(
            sql_text(
                "SELECT ts_rank_cd("
                "to_tsvector('simple'::regconfig, :document_text), "
                "plainto_tsquery('simple'::regconfig, :query), 0)"
            ),
            parameters,
        )

    assert fts_normalized_32 is not None
    assert trigram is not None
    assert fts_unnormalized is not None
    assert float(fts_normalized_32) != pytest.approx(float(fts_unnormalized))
    expected_score = 0.7 * float(fts_normalized_32) + 0.3 * float(trigram)
    assert evidence.lexical_score == pytest.approx(expected_score)
    assert evidence.retrieval_score == pytest.approx(expected_score)


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


def test_excerpt_maps_expanding_casefold_match_to_original_text_offset(
    migrated_engine: Engine,
) -> None:
    text = "ß" * 1500 + "NEEDLE" + "x" * 2494
    _persist_records(migrated_engine, _ChunkSpec(key=81, text=text))

    (evidence,) = _retrieve(migrated_engine, "NEEDLE")

    assert len(text) == 4000
    assert len(evidence.excerpt) == 2000
    assert evidence.excerpt == text[503:2503]
    assert "NEEDLE" in evidence.excerpt


def test_fts_only_match_excerpt_starts_at_the_beginning(
    migrated_engine: Engine,
) -> None:
    prefix = "pump synthetic maintenance "
    text = prefix + "x" * (4000 - len(prefix))
    _persist_records(migrated_engine, _ChunkSpec(key=82, text=text))

    (evidence,) = _retrieve(migrated_engine, "pump maintenance")

    assert "pump maintenance" not in text.casefold()
    assert len(evidence.excerpt) == 2000
    assert evidence.excerpt == text[:2000]


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


def test_successful_search_emits_no_mutation_and_releases_its_connection(
    migrated_engine: Engine,
) -> None:
    (chunk,) = _persist_records(
        migrated_engine,
        _ChunkSpec(key=90, text="read only transaction authorization matrix"),
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
        result = _retrieve(migrated_engine, "transaction authorization matrix")
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _capture)

    forbidden_statement_starts = (
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
    assert all(
        not statement.startswith(forbidden_statement_starts)
        for statement in executed
    )
    assert _document_row_counts(migrated_engine) == before_counts
    assert pool.checkedout() == 0


def test_database_failure_uses_a_fixed_cause_free_error(
    migrated_engine: Engine,
) -> None:
    unavailable_engine = create_engine(
        migrated_engine.url.set(host="127.0.0.1", port=1),
        connect_args={"connect_timeout": 1},
    )
    adapter = PostgresLexicalSearchAdapter(unavailable_engine)
    try:
        with pytest.raises(
            LexicalRetrievalError,
            match="^lexical retrieval unavailable$",
        ) as captured:
            adapter.search(
                "secret query text",
                AuthorizationScope(),
                KnowledgeFilters(),
                10,
            )
    finally:
        unavailable_engine.dispose()

    assert "secret query text" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert (
        captured.value.__context__ is None
        or captured.value.__suppress_context__
    )
