"""Public lexical retrieval contracts remain strict and transport-independent."""

import ast
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts import (
    AuthorizationScope,
    DocumentType,
    KnowledgeEvidence,
    KnowledgeFilters,
    SecurityLevel,
)
from services.retrieval import LexicalRetriever, RetrievalValidationError


def _evidence(**overrides: Any) -> KnowledgeEvidence:
    values: dict[str, Any] = {
        "document_id": UUID("a1000000-0000-0000-0000-000000000001"),
        "version_id": UUID("a1000000-0000-0000-0000-000000000002"),
        "chunk_id": UUID("a1000000-0000-0000-0000-000000000003"),
        "title": "Synthetic welding rule",
        "section": "4.2",
        "page": 7,
        "source_uri": "s3://synthetic/rule.pdf",
        "excerpt": "Synthetic welding clearance requirement.",
        "retrieval_score": 0.75,
        "lexical_score": 0.75,
    }
    values.update(overrides)
    return KnowledgeEvidence.model_validate(values)


def test_knowledge_evidence_is_frozen_and_preserves_provenance() -> None:
    evidence = _evidence()

    assert evidence.lexical_score == 0.75
    assert evidence.vector_score is None
    assert evidence.rerank_score is None
    with pytest.raises(ValidationError):
        cast(Any, evidence).title = "changed"


@pytest.mark.parametrize("field", ["title", "source_uri", "excerpt"])
@pytest.mark.parametrize("invalid_text", ["   ", "contains\x00nul"])
def test_knowledge_evidence_rejects_blank_or_nul_required_text(
    field: str, invalid_text: str
) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: invalid_text})


@pytest.mark.parametrize("invalid_section", ["   ", "contains\x00nul"])
def test_knowledge_evidence_rejects_blank_or_nul_section(invalid_section: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(section=invalid_section)


@pytest.mark.parametrize("invalid_page", [0, -1, True, 1.0])
def test_knowledge_evidence_requires_a_positive_exact_integer_page(
    invalid_page: object,
) -> None:
    with pytest.raises(ValidationError):
        _evidence(page=invalid_page)


@pytest.mark.parametrize(
    "score_field",
    ["retrieval_score", "lexical_score", "vector_score", "rerank_score"],
)
@pytest.mark.parametrize(
    "invalid_score", [-0.1, float("nan"), float("inf"), -float("inf")]
)
def test_knowledge_evidence_rejects_negative_or_nonfinite_scores(
    score_field: str, invalid_score: float
) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{score_field: invalid_score})


def test_knowledge_contracts_forbid_unknown_fields_and_are_frozen() -> None:
    with pytest.raises(ValidationError):
        KnowledgeEvidence.model_validate(
            {**_evidence().model_dump(), "untrusted_metadata": "injected"}
        )
    filters = KnowledgeFilters(document_type=DocumentType.PDF)
    with pytest.raises(ValidationError):
        cast(Any, filters).ship_id = UUID("a1000000-0000-0000-0000-000000000004")
    with pytest.raises(ValidationError):
        KnowledgeFilters.model_validate({"unexpected_filter": "injected"})


def test_knowledge_filters_accept_exact_document_types_and_uuid_filters() -> None:
    ship_id = UUID("a1000000-0000-0000-0000-000000000004")
    project_id = UUID("a1000000-0000-0000-0000-000000000005")

    for document_type in DocumentType:
        assert KnowledgeFilters(
            document_type=document_type,
            ship_id=ship_id,
            project_id=project_id,
        ) == KnowledgeFilters(
            document_type=document_type,
            ship_id=ship_id,
            project_id=project_id,
        )


type SearchCall = tuple[str, AuthorizationScope, KnowledgeFilters, int]


class RecordingLexicalPort:
    def __init__(self, result: list[KnowledgeEvidence]) -> None:
        self._result = result
        self.calls: list[SearchCall] = []

    def search(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]:
        self.calls.append((query, user_scope, filters, limit))
        return self._result


def _scope() -> AuthorizationScope:
    return AuthorizationScope(
        departments={"engineering"},
        allowed_ship_ids={"a1000000-0000-0000-0000-000000000010"},
        allowed_project_ids={"a1000000-0000-0000-0000-000000000011"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )


def test_lexical_retriever_validates_and_delegates_trusted_scope() -> None:
    scope = _scope()
    filters = KnowledgeFilters(document_type=DocumentType.PDF)
    port = RecordingLexicalPort([_evidence()])

    result = LexicalRetriever(port).retrieve(
        "  welding clearance  ", scope, filters, limit=7
    )

    assert result == [_evidence()]
    assert port.calls == [("welding clearance", scope, filters, 7)]


class _QuerySubclass(str):
    pass


class _ScopeSubclass(AuthorizationScope):
    pass


class _FiltersSubclass(KnowledgeFilters):
    pass


@pytest.mark.parametrize(
    ("query", "scope", "filters", "limit", "secret"),
    [
        (_QuerySubclass("welding"), _scope(), KnowledgeFilters(), 10, "welding"),
        ("   ", _scope(), KnowledgeFilters(), 10, "blank query"),
        ("contains\x00nul", _scope(), KnowledgeFilters(), 10, "contains\x00nul"),
        ("x" * 1001, _scope(), KnowledgeFilters(), 10, "x" * 1001),
        ("welding", _ScopeSubclass(), KnowledgeFilters(), 10, "scope value"),
        ("welding", _scope(), _FiltersSubclass(), 10, "filter value"),
        ("welding", _scope(), KnowledgeFilters(), True, "True"),
        ("welding", _scope(), KnowledgeFilters(), 1.0, "1.0"),
        ("welding", _scope(), KnowledgeFilters(), 0, "zero"),
        ("welding", _scope(), KnowledgeFilters(), 21, "twenty-one"),
    ],
)
def test_lexical_retriever_rejects_invalid_requests_before_calling_port(
    query: object,
    scope: object,
    filters: object,
    limit: object,
    secret: str,
) -> None:
    port = RecordingLexicalPort([])

    with pytest.raises(RetrievalValidationError) as captured:
        LexicalRetriever(port).retrieve(
            cast(str, query),
            cast(AuthorizationScope, scope),
            cast(KnowledgeFilters, filters),
            cast(int, limit),
        )

    assert str(captured.value) == "invalid lexical retrieval request"
    assert secret not in str(captured.value)
    assert port.calls == []


def _is_allowed_retrieval_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return False
    if node.level != 0:
        return False
    return node.module in {"__future__", "typing", "packages.contracts"}


def test_lexical_service_import_boundary_is_deny_by_default() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "services/retrieval/lexical.py"
    ).read_text(encoding="utf-8")
    malicious_relative = "from .. import infra as db"
    malicious_absolute = "from infra import postgres as db"

    assert all(
        _is_allowed_retrieval_import(node)
        for node in ast.parse(source).body
        if isinstance(node, ast.Import | ast.ImportFrom)
    )
    relative_node = ast.parse(malicious_relative).body[0]
    absolute_node = ast.parse(malicious_absolute).body[0]
    assert isinstance(relative_node, ast.ImportFrom)
    assert isinstance(absolute_node, ast.ImportFrom)
    assert not _is_allowed_retrieval_import(relative_node)
    assert not _is_allowed_retrieval_import(absolute_node)
