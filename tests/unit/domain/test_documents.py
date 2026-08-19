from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from packages.common import SecurityLevel as CommonSecurityLevel
from packages.contracts import SecurityLevel as ContractSecurityLevel
from packages.domain import (
    Document,
    DocumentChunk,
    DocumentValidationError,
    DocumentVersion,
    document_chunk_id,
)

DOCUMENT_ID = UUID("90000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("90000000-0000-0000-0000-000000000002")
UPDATED_AT = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


def _document(**changes: object) -> Document:
    values: dict[str, object] = {
        "document_id": DOCUMENT_ID,
        "source_system": "synthetic-plm",
        "source_id": "rule-a",
        "title": "Synthetic Class Rule A",
    }
    values.update(changes)
    return Document(**values)  # type: ignore[arg-type]


def _version(**changes: object) -> DocumentVersion:
    values: dict[str, object] = {
        "version_id": VERSION_ID,
        "document_id": DOCUMENT_ID,
        "checksum": "a" * 64,
        "source_uri": "s3://synthetic-documents/rule-a.pdf",
        "source_updated_at": UPDATED_AT,
        "security_level": CommonSecurityLevel.INTERNAL,
        "ship_id": UUID("90000000-0000-0000-0000-000000000003"),
        "project_id": UUID("90000000-0000-0000-0000-000000000004"),
        "department": "Synthetic Engineering",
    }
    values.update(changes)
    return DocumentVersion(**values)  # type: ignore[arg-type]


def _chunk(**changes: object) -> DocumentChunk:
    values: dict[str, object] = {
        "chunk_id": document_chunk_id(
            VERSION_ID,
            ("Chapter 1", "a/b"),
            0,
        ),
        "version_id": VERSION_ID,
        "structural_path": ("Chapter 1", "a/b"),
        "ordinal": 0,
        "normalized_text": "Synthetic class-rule paragraph.",
        "page": 1,
        "section": "Chapter 1",
    }
    values.update(changes)
    return DocumentChunk(**values)  # type: ignore[arg-type]


def test_security_level_is_one_shared_framework_independent_type() -> None:
    assert CommonSecurityLevel is ContractSecurityLevel
    assert [level.value for level in CommonSecurityLevel] == [0, 1, 2, 3]


def test_document_is_immutable_and_preserves_external_identity() -> None:
    document = _document()

    assert document.document_id == DOCUMENT_ID
    assert document.source_system == "synthetic-plm"
    assert document.source_id == "rule-a"
    with pytest.raises(FrozenInstanceError):
        document.title = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["source_system", "source_id", "title"])
def test_document_rejects_blank_required_text(field: str) -> None:
    with pytest.raises(DocumentValidationError, match=rf"^{field} must be non-blank$"):
        _document(**{field: " "})


def test_document_version_is_immutable_and_preserves_acl_metadata() -> None:
    version = _version()
    assert version.ship_id == UUID("90000000-0000-0000-0000-000000000003")
    assert version.project_id == UUID("90000000-0000-0000-0000-000000000004")
    assert version.department == "Synthetic Engineering"
    with pytest.raises(FrozenInstanceError):
        version.checksum = "b" * 64  # type: ignore[misc]


def test_document_chunk_id_is_stable_and_path_boundary_safe() -> None:
    first = document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 0)
    assert first == document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 0)
    assert first != document_chunk_id(VERSION_ID, ("Chapter 1", "a", "b"), 0)
    assert first != document_chunk_id(VERSION_ID, ("Chapter 1", "a/b"), 1)
    chunk = DocumentChunk(
        chunk_id=first,
        version_id=VERSION_ID,
        structural_path=("Chapter 1", "a/b"),
        ordinal=0,
        normalized_text="Synthetic class-rule paragraph.",
        page=1,
        section="Chapter 1",
    )
    assert chunk.chunk_id == first


def test_document_chunk_accepts_empty_path_and_is_immutable() -> None:
    chunk = DocumentChunk(
        chunk_id=document_chunk_id(VERSION_ID, (), 0),
        version_id=VERSION_ID,
        structural_path=(),
        ordinal=0,
        normalized_text="Synthetic unstructured fallback paragraph.",
    )

    assert chunk.structural_path == ()
    with pytest.raises(FrozenInstanceError):
        chunk.normalized_text = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"checksum": "A" * 64}, "checksum must be lowercase SHA-256 text"),
        ({"checksum": "a" * 63}, "checksum must be lowercase SHA-256 text"),
        ({"source_uri": "  "}, "source_uri must be non-blank"),
        (
            {"source_updated_at": datetime(2026, 8, 19, 8, 0)},
            "source_updated_at must be timezone-aware",
        ),
        ({"security_level": 1}, "security_level must be a SecurityLevel"),
        ({"department": " "}, "department must be non-blank when provided"),
    ],
)
def test_document_version_rejects_invalid_metadata(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(DocumentValidationError, match=f"^{message}$"):
        _version(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"structural_path": ["Chapter 1"]}, "structural_path must be a tuple"),
        ({"structural_path": (" ",)}, "structural_path elements must be non-blank"),
        ({"ordinal": -1}, "ordinal must be a non-negative integer"),
        ({"ordinal": True}, "ordinal must be a non-negative integer"),
        ({"page": 0}, "page must be a positive integer when provided"),
        ({"page": True}, "page must be a positive integer when provided"),
        ({"normalized_text": " "}, "normalized_text must be non-blank"),
        ({"section": " "}, "section must be non-blank when provided"),
        (
            {"chunk_id": UUID("90000000-0000-0000-0000-000000000099")},
            "chunk_id is not deterministic",
        ),
    ],
)
def test_document_chunk_rejects_invalid_metadata(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(DocumentValidationError, match=f"^{message}$"):
        _chunk(**changes)


def test_document_chunk_id_rejects_non_tuple_path_and_boolean_ordinal() -> None:
    with pytest.raises(
        DocumentValidationError, match="^structural_path must be a tuple$"
    ):
        document_chunk_id(VERSION_ID, cast(Any, ["Chapter 1"]), 0)
    with pytest.raises(
        DocumentValidationError, match="^ordinal must be a non-negative integer$"
    ):
        document_chunk_id(VERSION_ID, ("Chapter 1",), cast(Any, True))
