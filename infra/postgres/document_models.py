"""SQLAlchemy persistence models for immutable document metadata."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from infra.postgres.models import Base


class DocumentModel(Base):
    """Stable logical identity for an externally sourced document."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_id",
            name="uq_documents_source_identity",
        ),
        CheckConstraint(
            "btrim(source_system) <> ''", name="ck_documents_source_system"
        ),
        CheckConstraint("btrim(source_id) <> ''", name="ck_documents_source_id"),
        CheckConstraint("btrim(title) <> ''", name="ck_documents_title"),
    )

    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)


class DocumentVersionModel(Base):
    """Immutable content and authorization snapshot of a Document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "checksum",
            name="uq_document_versions_document_checksum",
        ),
        CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_checksum",
        ),
        CheckConstraint(
            "btrim(source_uri) <> ''",
            name="ck_document_versions_source_uri",
        ),
        CheckConstraint(
            "security_level BETWEEN 0 AND 3",
            name="ck_document_versions_security_level",
        ),
        CheckConstraint(
            "department IS NULL OR btrim(department) <> ''",
            name="ck_document_versions_department",
        ),
    )

    version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "documents.document_id", name="fk_document_versions_document_id"
        ),
        nullable=False,
        index=True,
    )
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    security_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, index=True
    )
    ship_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_document_versions_ship_id"),
        index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    department: Mapped[str | None] = mapped_column(Text, index=True)


class DocumentChunkModel(Base):
    """Deterministic structural location inside a DocumentVersion."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "structural_path",
            "ordinal",
            name="uq_document_chunks_structural_location",
        ),
        CheckConstraint(
            "array_position(structural_path, NULL) IS NULL "
            "AND array_position(structural_path, '') IS NULL",
            name="ck_document_chunks_path_elements",
        ),
        CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal"),
        CheckConstraint(
            "btrim(normalized_text) <> ''", name="ck_document_chunks_text"
        ),
        CheckConstraint(
            "page IS NULL OR page > 0", name="ck_document_chunks_page"
        ),
        CheckConstraint(
            "section IS NULL OR btrim(section) <> ''",
            name="ck_document_chunks_section",
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "document_versions.version_id",
            name="fk_document_chunks_version_id",
        ),
        nullable=False,
        index=True,
    )
    structural_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, index=True)
    section: Mapped[str | None] = mapped_column(Text)
