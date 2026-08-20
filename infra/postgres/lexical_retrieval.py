"""ACL-filtered PostgreSQL lexical retrieval over immutable chunks."""

from __future__ import annotations

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
from infra.postgres.retrieval_support import (
    authorized_document_constraints,
    evidence_excerpt,
)
from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters
from services.retrieval.lexical import LexicalRetrievalError, LexicalSearchPort

LEXICAL_FTS_WEIGHT = 0.7
LEXICAL_TRIGRAM_WEIGHT = 0.3
LEXICAL_STATEMENT_TIMEOUT_MS = 2000
_UNAVAILABLE = "lexical retrieval unavailable"
_SIMPLE_CONFIG: ColumnClause[str] = literal_column("'simple'::regconfig")


def _literal_ilike_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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

        authorization_predicates, authorization_parameters = (
            authorized_document_constraints(user_scope, filters)
        )
        predicates = [
            or_(
                vector.op("@@")(plain_query),
                DocumentChunkModel.normalized_text.ilike(
                    bindparam("literal_pattern"), escape="\\"
                ),
            ),
            *authorization_predicates,
        ]
        parameters: dict[str, object] = {
            **authorization_parameters,
            "query": query,
            "literal_pattern": _literal_ilike_pattern(query),
            "limit": limit,
        }

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
                    excerpt=evidence_excerpt(row.normalized_text, query),
                    retrieval_score=score,
                    lexical_score=score,
                )
            )
        return evidence
