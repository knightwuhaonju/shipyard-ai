"""Shared ACL, filter, and evidence support for PostgreSQL retrieval."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import bindparam, or_
from sqlalchemy.sql.elements import ColumnElement

from infra.postgres.document_models import DocumentVersionModel
from packages.contracts import AuthorizationScope, KnowledgeFilters

_MAX_EVIDENCE_EXCERPT_CHARS = 2000


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


def authorized_document_constraints(
    user_scope: AuthorizationScope,
    filters: KnowledgeFilters,
) -> tuple[tuple[ColumnElement[bool], ...], dict[str, object]]:
    """Build intersecting document ACL/filter predicates and bound parameters."""
    predicates = [
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
        "scope_security_level": user_scope.security_level.value,
        "scope_departments": tuple(sorted(user_scope.departments)),
        "scope_ship_ids": _canonical_scope_uuids(user_scope.allowed_ship_ids),
        "scope_project_ids": _canonical_scope_uuids(
            user_scope.allowed_project_ids
        ),
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

    return tuple(predicates), parameters


def _casefold_match_span(text_value: str, query: str) -> tuple[int, int] | None:
    folded_parts: list[str] = []
    original_offsets: list[int] = []
    for original_offset, character in enumerate(text_value):
        folded_character = character.casefold()
        folded_parts.append(folded_character)
        original_offsets.extend([original_offset] * len(folded_character))

    folded_query = query.casefold()
    folded_match = "".join(folded_parts).find(folded_query)
    if folded_match < 0 or not folded_query:
        return None
    match_end = folded_match + len(folded_query) - 1
    return original_offsets[folded_match], original_offsets[match_end] + 1


def evidence_excerpt(text_value: str, query: str) -> str:
    """Return the existing bounded excerpt around a Unicode-folded match."""
    if len(text_value) <= _MAX_EVIDENCE_EXCERPT_CHARS:
        return text_value
    match_span = _casefold_match_span(text_value, query)
    if match_span is None:
        start = 0
    else:
        match_start, match_end = match_span
        centered_start = (
            (match_start + match_end) // 2
            - _MAX_EVIDENCE_EXCERPT_CHARS // 2
        )
        start = max(
            0,
            min(
                centered_start,
                len(text_value) - _MAX_EVIDENCE_EXCERPT_CHARS,
            ),
        )
    return text_value[start : start + _MAX_EVIDENCE_EXCERPT_CHARS]
