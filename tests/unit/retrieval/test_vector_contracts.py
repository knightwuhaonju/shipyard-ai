"""Vector retrieval orchestration stays strict and transport-independent."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from adapters.embedding import FakeEmbeddingAdapter
from packages.contracts import (
    AuthorizationScope,
    KnowledgeEvidence,
    KnowledgeFilters,
    SecurityLevel,
)
from services.model_gateway import EmbeddingGateway, EmbeddingProfile
from services.retrieval import (
    VectorRetrievalError,
    VectorRetrievalValidationError,
    VectorRetriever,
)


def _evidence(**overrides: Any) -> KnowledgeEvidence:
    values: dict[str, Any] = {
        "document_id": UUID("b1000000-0000-0000-0000-000000000001"),
        "version_id": UUID("b1000000-0000-0000-0000-000000000002"),
        "chunk_id": UUID("b1000000-0000-0000-0000-000000000003"),
        "title": "Synthetic ballast rule",
        "section": "4.2",
        "page": 7,
        "source_uri": "s3://synthetic/ballast-rule.pdf",
        "excerpt": "Synthetic ballast pump clearance requirement.",
        "retrieval_score": 0.95,
        "vector_score": 0.95,
    }
    values.update(overrides)
    return KnowledgeEvidence.model_validate(values)


type SearchCall = tuple[
    str,
    tuple[float, ...],
    EmbeddingProfile,
    AuthorizationScope,
    KnowledgeFilters,
    int,
]


class RecordingVectorPort:
    def __init__(self, result: list[KnowledgeEvidence]) -> None:
        self._result = result
        self.calls: list[SearchCall] = []

    def search(
        self,
        query: str,
        query_embedding: tuple[float, ...],
        profile: EmbeddingProfile,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]:
        self.calls.append(
            (query, query_embedding, profile, user_scope, filters, limit)
        )
        return self._result


def _profile() -> EmbeddingProfile:
    return EmbeddingProfile(model_id="fake-deterministic-v1", dimension=8)


def _scope() -> AuthorizationScope:
    return AuthorizationScope(
        departments={"engineering"},
        allowed_ship_ids={"b1000000-0000-0000-0000-000000000010"},
        allowed_project_ids={"b1000000-0000-0000-0000-000000000011"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )


def test_vector_retriever_embeds_once_and_delegates_trusted_scope() -> None:
    profile = _profile()
    query_vector = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    fake = FakeEmbeddingAdapter(profile, {"ballast pump": query_vector})
    gateway = EmbeddingGateway(fake)
    port = RecordingVectorPort([_evidence(vector_score=0.95)])
    scope = _scope()
    filters = KnowledgeFilters()

    result = VectorRetriever(gateway, port).retrieve(
        "  ballast pump  ", scope, filters, limit=7
    )

    assert result == [_evidence(vector_score=0.95)]
    assert fake.calls == (("ballast pump",),)
    assert port.calls == [
        ("ballast pump", query_vector, profile, scope, filters, 7)
    ]


class _QuerySubclass(str):
    pass


class _ScopeSubclass(AuthorizationScope):
    pass


class _FiltersSubclass(KnowledgeFilters):
    pass


@pytest.mark.parametrize(
    ("query", "scope", "filters", "limit", "secret"),
    [
        (42, _scope(), KnowledgeFilters(), 10, "42"),
        (_QuerySubclass("ballast"), _scope(), KnowledgeFilters(), 10, "ballast"),
        ("   ", _scope(), KnowledgeFilters(), 10, "blank query"),
        ("contains\x00nul", _scope(), KnowledgeFilters(), 10, "contains\x00nul"),
        ("x" * 1001, _scope(), KnowledgeFilters(), 10, "x" * 1001),
        ("ballast", _ScopeSubclass(), KnowledgeFilters(), 10, "scope value"),
        ("ballast", _scope(), _FiltersSubclass(), 10, "filter value"),
        ("ballast", _scope(), KnowledgeFilters(), True, "True"),
        ("ballast", _scope(), KnowledgeFilters(), 1.0, "1.0"),
        ("ballast", _scope(), KnowledgeFilters(), 0, "zero"),
        ("ballast", _scope(), KnowledgeFilters(), 21, "twenty-one"),
    ],
)
def test_vector_retriever_rejects_invalid_requests_before_any_dependency_call(
    query: object,
    scope: object,
    filters: object,
    limit: object,
    secret: str,
) -> None:
    profile = _profile()
    fake = FakeEmbeddingAdapter(
        profile,
        {"ballast": (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)},
    )
    port = RecordingVectorPort([])

    with pytest.raises(VectorRetrievalValidationError) as captured:
        VectorRetriever(EmbeddingGateway(fake), port).retrieve(
            cast(str, query),
            cast(AuthorizationScope, scope),
            cast(KnowledgeFilters, filters),
            cast(int, limit),
        )

    assert str(captured.value) == "invalid vector retrieval request"
    assert secret not in str(captured.value)
    assert fake.calls == ()
    assert port.calls == []


@pytest.mark.parametrize("limit", [1, 20])
def test_vector_retriever_accepts_exact_limit_boundaries(limit: int) -> None:
    profile = _profile()
    query_vector = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    fake = FakeEmbeddingAdapter(profile, {"ballast": query_vector})
    port = RecordingVectorPort([])

    VectorRetriever(EmbeddingGateway(fake), port).retrieve(
        "ballast", _scope(), KnowledgeFilters(), limit
    )

    assert port.calls == [
        ("ballast", query_vector, profile, _scope(), KnowledgeFilters(), limit)
    ]


def test_vector_retriever_translates_only_typed_embedding_failure() -> None:
    secret_model = "model-secret-a81f"
    profile = EmbeddingProfile(model_id=secret_model, dimension=8)
    fake = FakeEmbeddingAdapter(profile, {})
    port = RecordingVectorPort([])

    with pytest.raises(
        VectorRetrievalError, match="^vector retrieval unavailable$"
    ) as captured:
        VectorRetriever(EmbeddingGateway(fake), port).retrieve(
            "secret ballast query", _scope(), KnowledgeFilters()
        )

    assert "secret ballast query" not in str(captured.value)
    assert secret_model not in str(captured.value)
    assert fake.calls == (("secret ballast query",),)
    assert port.calls == []
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None or captured.value.__suppress_context__


class _ProgrammingFailureAdapter:
    @property
    def profile(self) -> EmbeddingProfile:
        return _profile()

    def embed(self, _texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise TypeError("programming failure sentinel")


class _ProgrammingFailurePort(RecordingVectorPort):
    def search(
        self,
        query: str,
        query_embedding: tuple[float, ...],
        profile: EmbeddingProfile,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]:
        raise LookupError("port programming failure sentinel")


def test_vector_retriever_does_not_translate_embedding_programming_errors() -> None:
    gateway = EmbeddingGateway(_ProgrammingFailureAdapter())

    with pytest.raises(TypeError, match="^programming failure sentinel$"):
        VectorRetriever(gateway, RecordingVectorPort([])).retrieve(
            "ballast", _scope(), KnowledgeFilters()
        )


def test_vector_retriever_does_not_translate_port_programming_errors() -> None:
    profile = _profile()
    fake = FakeEmbeddingAdapter(
        profile,
        {"ballast": (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)},
    )

    with pytest.raises(LookupError, match="^port programming failure sentinel$"):
        VectorRetriever(
            EmbeddingGateway(fake), _ProgrammingFailurePort([])
        ).retrieve("ballast", _scope(), KnowledgeFilters())


def _is_allowed_vector_service_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return False
    allowed_symbols = {
        "__future__": {"annotations"},
        "typing": {"Protocol"},
        "packages.contracts": {
            "AuthorizationScope",
            "KnowledgeEvidence",
            "KnowledgeFilters",
        },
        "services.model_gateway": {
            "EmbeddingGateway",
            "EmbeddingProfile",
            "EmbeddingUnavailableError",
        },
    }
    if node.level != 0 or node.module not in allowed_symbols:
        return False
    return all(
        alias.asname is None
        and alias.name != "*"
        and alias.name in allowed_symbols[node.module]
        for alias in node.names
    )


def _uses_only_allowed_top_level_vector_service_imports(source: str) -> bool:
    tree = ast.parse(source)
    top_level_import_ids = {
        id(node) for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
    }
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    return all(
        id(node) in top_level_import_ids and _is_allowed_vector_service_import(node)
        for node in imports
    )


def test_vector_service_import_boundary_is_complete_and_deny_by_default() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "services/retrieval/vector.py"
    ).read_text(encoding="utf-8")

    assert _uses_only_allowed_top_level_vector_service_imports(source)


@pytest.mark.parametrize(
    "malicious_source",
    [
        "if enabled:\n    from infra import postgres\n",
        "try:\n    from openai import OpenAI\nexcept ImportError:\n    pass\n",
        "from services.ingestion import Parser\n",
        "from services.retrieval.hybrid import HybridRetriever\n",
        "from services.retrieval.reranker import Reranker\n",
        "from services.wiki import WikiSearch\n",
        "from services.agent import ShipyardAgent\n",
        "from apps.api import app\n",
        "from packages.contracts import UserContext\n",
        "from services.model_gateway import EmbeddingGateway as Gateway\n",
        "import typing\n",
    ],
)
def test_vector_service_import_guard_rejects_all_unapproved_imports(
    malicious_source: str,
) -> None:
    assert not _uses_only_allowed_top_level_vector_service_imports(
        malicious_source
    )


def _is_allowed_postgres_vector_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return False
    allowed_symbols = {
        "__future__": {"annotations"},
        "math": {"isfinite"},
        "sqlalchemy": {"bindparam", "select", "text"},
        "sqlalchemy.engine": {"Engine"},
        "sqlalchemy.exc": {"SQLAlchemyError"},
        "sqlalchemy.orm": {"Session"},
        "infra.postgres.document_models": {
            "DATABASE_EMBEDDING_DIMENSION",
            "DATABASE_EMBEDDING_MODEL_ID",
            "DocumentChunkEmbeddingModel",
            "DocumentChunkModel",
            "DocumentModel",
            "DocumentVersionModel",
        },
        "infra.postgres.retrieval_support": {
            "authorized_document_constraints",
            "evidence_excerpt",
        },
        "packages.contracts": {
            "AuthorizationScope",
            "KnowledgeEvidence",
            "KnowledgeFilters",
        },
        "services.model_gateway": {"EmbeddingProfile"},
        "services.retrieval.vector": {
            "VectorRetrievalError",
            "VectorSearchPort",
        },
    }
    if node.level != 0 or node.module not in allowed_symbols:
        return False
    return all(
        alias.asname is None
        and alias.name != "*"
        and alias.name in allowed_symbols[node.module]
        for alias in node.names
    )


def _uses_only_allowed_top_level_postgres_vector_imports(source: str) -> bool:
    tree = ast.parse(source)
    top_level_import_ids = {
        id(node) for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
    }
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    return all(
        id(node) in top_level_import_ids and _is_allowed_postgres_vector_import(node)
        for node in imports
    )


def test_postgres_vector_import_boundary_is_complete_and_deny_by_default() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "infra/postgres/vector_retrieval.py"
    ).read_text(encoding="utf-8")

    assert _uses_only_allowed_top_level_postgres_vector_imports(source)


@pytest.mark.parametrize(
    "malicious_source",
    [
        "if enabled:\n    from sqlalchemy import select\n",
        "try:\n    from openai import OpenAI\nexcept ImportError:\n    pass\n",
        "from services.ingestion import Parser\n",
        "from adapters.embedding import FakeEmbeddingAdapter\n",
        "from services.retrieval.hybrid import HybridRetriever\n",
        "from services.retrieval.reranker import Reranker\n",
        "from services.wiki import WikiSearch\n",
        "from services.agent import ShipyardAgent\n",
        "from apps.api import app\n",
        "from adapters.erp import ErpAdapter\n",
        "from packages.contracts import UserContext\n",
        "from infra.postgres import DocumentModel\n",
        "from .document_models import DocumentModel\n",
        "import sqlalchemy\n",
    ],
)
def test_postgres_vector_import_guard_rejects_all_unapproved_imports(
    malicious_source: str,
) -> None:
    assert not _uses_only_allowed_top_level_postgres_vector_imports(
        malicious_source
    )
