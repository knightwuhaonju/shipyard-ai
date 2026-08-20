"""ACL-filtered PostgreSQL lexical retrieval over immutable chunks."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import bindparam, func, literal_column, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnClause

from infra.postgres.document_models import (
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters
from services.retrieval.lexical import LexicalRetrievalError, LexicalSearchPort

LEXICAL_FTS_WEIGHT = 0.7
LEXICAL_TRIGRAM_WEIGHT = 0.3
LEXICAL_STATEMENT_TIMEOUT_MS = 2000
MAX_EVIDENCE_EXCERPT_CHARS = 2000
_UNAVAILABLE = "lexical retrieval unavailable"
_SIMPLE_CONFIG: ColumnClause[str] = literal_column("'simple'::regconfig")


def _canonical_scope_uuids(values: Iterable[str]) -> tuple[UUID, ...]:
    canonical: set[UUID] = set()
    for value in values:
        try:
            parsed = UUID(value)
        except ValueError:
            continue
        if str(parsed) == value.lower():
            canonical.add(parsed)
    return tuple(sorted(canonical, key=str))


def _literal_ilike_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _excerpt(text_value: str, query: str) -> str:
    if len(text_value) <= MAX_EVIDENCE_EXCERPT_CHARS:
        return text_value
    match_index = text_value.casefold().find(query.casefold())
    if match_index < 0:
        start = 0
    else:
        centered_start = (
            match_index + len(query) // 2 - MAX_EVIDENCE_EXCERPT_CHARS // 2
        )
        start = max(
            0,
            min(centered_start, len(text_value) - MAX_EVIDENCE_EXCERPT_CHARS),
        )
    return text_value[start : start + MAX_EVIDENCE_EXCERPT_CHARS]


class PostgresLexicalSearchAdapter(LexicalSearchPort):
    """Execute one bounded ACL-aware candidate query in a private session."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]:
        plain_query = func.plainto_tsquery(_SIMPLE_CONFIG, bindparam("query"))
        vector = func.to_tsvector(
            _SIMPLE_CONFIG, DocumentChunkModel.normalized_text
        )
        fts_score = func.ts_rank_cd(vector, plain_query, 32)
        trigram_score = func.similarity(
            DocumentChunkModel.normalized_text, bindparam("query")
        )
        lexical_score = (
            LEXICAL_FTS_WEIGHT * fts_score
            + LEXICAL_TRIGRAM_WEIGHT * trigram_score
        ).label("lexical_score")

        predicates = [
            or_(
                vector.op("@@")(plain_query),
                DocumentChunkModel.normalized_text.ilike(
                    bindparam("literal_pattern"), escape="\\"
                ),
            ),
            DocumentVersionModel.security_level
            <= bindparam("scope_security_level"),
            or_(
                DocumentVersionModel.department.is_(None),
                DocumentVersionModel.department.in_(
                    bindparam("scope_departments", expanding=True)
                ),
            ),
            or_(
                DocumentVersionModel.ship_id.is_(None),
                DocumentVersionModel.ship_id.in_(
                    bindparam("scope_ship_ids", expanding=True)
                ),
            ),
            or_(
                DocumentVersionModel.project_id.is_(None),
                DocumentVersionModel.project_id.in_(
                    bindparam("scope_project_ids", expanding=True)
                ),
            ),
        ]
        parameters: dict[str, object] = {
            "query": query,
            "literal_pattern": _literal_ilike_pattern(query),
            "scope_security_level": user_scope.security_level.value,
            "scope_departments": tuple(sorted(user_scope.departments)),
            "scope_ship_ids": _canonical_scope_uuids(user_scope.allowed_ship_ids),
            "scope_project_ids": _canonical_scope_uuids(
                user_scope.allowed_project_ids
            ),
            "limit": limit,
        }
        if filters.document_type is not None:
            predicates.append(
                DocumentVersionModel.document_type == bindparam("document_type")
            )
            parameters["document_type"] = filters.document_type.value
        if filters.ship_id is not None:
            predicates.append(DocumentVersionModel.ship_id == bindparam("ship_id"))
            parameters["ship_id"] = filters.ship_id
        if filters.project_id is not None:
            predicates.append(
                DocumentVersionModel.project_id == bindparam("project_id")
            )
            parameters["project_id"] = filters.project_id

        statement = (
            select(
                DocumentModel.document_id.label("document_id"),
                DocumentVersionModel.version_id.label("version_id"),
                DocumentChunkModel.chunk_id.label("chunk_id"),
                DocumentModel.title.label("title"),
                DocumentChunkModel.section.label("section"),
                DocumentChunkModel.page.label("page"),
                DocumentVersionModel.source_uri.label("source_uri"),
                DocumentChunkModel.normalized_text.label("normalized_text"),
                lexical_score,
            )
            .select_from(DocumentChunkModel)
            .join(
                DocumentVersionModel,
                DocumentVersionModel.version_id == DocumentChunkModel.version_id,
            )
            .join(
                DocumentModel,
                DocumentModel.document_id == DocumentVersionModel.document_id,
            )
            .where(*predicates)
            .order_by(
                lexical_score.desc(),
                DocumentVersionModel.source_updated_at.desc(),
                DocumentChunkModel.chunk_id.asc(),
            )
            .limit(bindparam("limit"))
        )

        try:
            with Session(self._engine) as session, session.begin():
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.scalar(
                    select(
                        func.set_config(
                            "statement_timeout",
                            str(LEXICAL_STATEMENT_TIMEOUT_MS),
                            True,
                        )
                    )
                )
                rows = session.execute(statement, parameters).all()
        except SQLAlchemyError:
            raise LexicalRetrievalError(_UNAVAILABLE) from None

        evidence: list[KnowledgeEvidence] = []
        for row in rows:
            score = max(0.0, float(row.lexical_score))
            evidence.append(
                KnowledgeEvidence(
                    document_id=row.document_id,
                    version_id=row.version_id,
                    chunk_id=row.chunk_id,
                    title=row.title,
                    section=row.section,
                    page=row.page,
                    source_uri=row.source_uri,
                    excerpt=_excerpt(row.normalized_text, query),
                    retrieval_score=score,
                    lexical_score=score,
                )
            )
        return evidence
