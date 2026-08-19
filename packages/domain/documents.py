"""Immutable document knowledge-plane records and deterministic chunk IDs."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from packages.common.security import SecurityLevel

_CHUNK_ID_NAMESPACE = UUID("90f13714-cfb7-5871-a2ef-92c413d6e55e")
_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class DocumentValidationError(ValueError):
    """Raised when a document domain record has invalid metadata."""


def _require_uuid(field: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise DocumentValidationError(f"{field} must be a UUID")


def _require_text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DocumentValidationError(f"{field} must be non-blank")


def _require_optional_text(field: str, value: object | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DocumentValidationError(f"{field} must be non-blank when provided")


def _require_optional_uuid(field: str, value: object | None) -> None:
    if value is not None:
        _require_uuid(field, value)


def _require_timezone_aware(field: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DocumentValidationError(f"{field} must be timezone-aware")


def _require_structural_path(value: object) -> None:
    if not isinstance(value, tuple):
        raise DocumentValidationError("structural_path must be a tuple")
    if any(not isinstance(element, str) or not element.strip() for element in value):
        raise DocumentValidationError("structural_path elements must be non-blank")


def _require_non_negative_integer(field: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise DocumentValidationError(f"{field} must be a non-negative integer")


def _require_optional_positive_integer(field: str, value: object | None) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise DocumentValidationError(
            f"{field} must be a positive integer when provided"
        )


def document_chunk_id(
    version_id: UUID,
    structural_path: tuple[str, ...],
    ordinal: int,
) -> UUID:
    _require_uuid("version_id", version_id)
    _require_structural_path(structural_path)
    _require_non_negative_integer("ordinal", ordinal)
    payload = json.dumps(
        {
            "ordinal": ordinal,
            "structural_path": structural_path,
            "version_id": str(version_id),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return uuid5(_CHUNK_ID_NAMESPACE, payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class Document:
    document_id: UUID
    source_system: str
    source_id: str
    title: str

    def __post_init__(self) -> None:
        _require_uuid("document_id", self.document_id)
        _require_text("source_system", self.source_system)
        _require_text("source_id", self.source_id)
        _require_text("title", self.title)


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentVersion:
    version_id: UUID
    document_id: UUID
    checksum: str
    source_uri: str
    source_updated_at: datetime
    security_level: SecurityLevel
    ship_id: UUID | None = None
    project_id: UUID | None = None
    department: str | None = None

    def __post_init__(self) -> None:
        _require_uuid("version_id", self.version_id)
        _require_uuid("document_id", self.document_id)
        if (
            not isinstance(self.checksum, str)
            or _SHA256.fullmatch(self.checksum) is None
        ):
            raise DocumentValidationError("checksum must be lowercase SHA-256 text")
        _require_text("source_uri", self.source_uri)
        _require_timezone_aware("source_updated_at", self.source_updated_at)
        if not isinstance(self.security_level, SecurityLevel):
            raise DocumentValidationError("security_level must be a SecurityLevel")
        _require_optional_uuid("ship_id", self.ship_id)
        _require_optional_uuid("project_id", self.project_id)
        _require_optional_text("department", self.department)


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentChunk:
    chunk_id: UUID
    version_id: UUID
    structural_path: tuple[str, ...]
    ordinal: int
    normalized_text: str
    page: int | None = None
    section: str | None = None

    def __post_init__(self) -> None:
        _require_uuid("chunk_id", self.chunk_id)
        _require_uuid("version_id", self.version_id)
        _require_structural_path(self.structural_path)
        _require_non_negative_integer("ordinal", self.ordinal)
        _require_text("normalized_text", self.normalized_text)
        _require_optional_positive_integer("page", self.page)
        _require_optional_text("section", self.section)
        if self.chunk_id != document_chunk_id(
            self.version_id, self.structural_path, self.ordinal
        ):
            raise DocumentValidationError("chunk_id is not deterministic")
