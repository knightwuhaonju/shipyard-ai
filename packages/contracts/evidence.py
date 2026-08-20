"""Transport-independent knowledge retrieval evidence contracts."""

from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
)

from packages.common import DocumentType

__all__ = ["DocumentType", "KnowledgeEvidence", "KnowledgeFilters"]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KnowledgeFilters(_FrozenContract):
    """Optional metadata predicates for authorized knowledge retrieval."""

    document_type: DocumentType | None = None
    ship_id: UUID | None = None
    project_id: UUID | None = None


class KnowledgeEvidence(_FrozenContract):
    """Traceable evidence from an authorized immutable document chunk."""

    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    section: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ] | None = None
    page: Annotated[StrictInt, Field(gt=0)] | None = None
    source_uri: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]
    excerpt: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    retrieval_score: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    lexical_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    vector_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    rerank_score: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None

    @field_validator("title", "section", "source_uri", "excerpt")
    @classmethod
    def _reject_nul_text(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("text fields must not contain NUL")
        return value
