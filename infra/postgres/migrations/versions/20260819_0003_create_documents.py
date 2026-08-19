"""create document metadata tables

Revision ID: 20260819_0003
Revises: 20260818_0002
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260819_0003"
down_revision: str | Sequence[str] | None = "20260818_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "btrim(source_system) <> ''", name="ck_documents_source_system"
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> ''", name="ck_documents_source_id"
        ),
        sa.CheckConstraint("btrim(title) <> ''", name="ck_documents_title"),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint(
            "source_system",
            "source_id",
            name="uq_documents_source_identity",
        ),
    )
    op.create_table(
        "document_versions",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column(
            "source_updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("security_level", sa.SmallInteger(), nullable=False),
        sa.Column("ship_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_checksum",
        ),
        sa.CheckConstraint(
            "department IS NULL OR btrim(department) <> ''",
            name="ck_document_versions_department",
        ),
        sa.CheckConstraint(
            "security_level BETWEEN 0 AND 3",
            name="ck_document_versions_security_level",
        ),
        sa.CheckConstraint(
            "btrim(source_uri) <> ''",
            name="ck_document_versions_source_uri",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_document_versions_document_id",
        ),
        sa.ForeignKeyConstraint(
            ["ship_id"],
            ["ships.id"],
            name="fk_document_versions_ship_id",
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint(
            "document_id",
            "checksum",
            name="uq_document_versions_document_checksum",
        ),
    )
    op.create_index(
        "ix_document_versions_department",
        "document_versions",
        ["department"],
        unique=False,
    )
    op.create_index(
        "ix_document_versions_document_id",
        "document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_versions_project_id",
        "document_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_versions_security_level",
        "document_versions",
        ["security_level"],
        unique=False,
    )
    op.create_index(
        "ix_document_versions_ship_id",
        "document_versions",
        ["ship_id"],
        unique=False,
    )
    op.create_table(
        "document_chunks",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column(
            "structural_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "ordinal >= 0", name="ck_document_chunks_ordinal"
        ),
        sa.CheckConstraint(
            "page IS NULL OR page > 0", name="ck_document_chunks_page"
        ),
        sa.CheckConstraint(
            "array_position(structural_path, NULL) IS NULL "
            "AND array_position(structural_path, '') IS NULL",
            name="ck_document_chunks_path_elements",
        ),
        sa.CheckConstraint(
            "section IS NULL OR btrim(section) <> ''",
            name="ck_document_chunks_section",
        ),
        sa.CheckConstraint(
            "btrim(normalized_text) <> ''", name="ck_document_chunks_text"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            name="fk_document_chunks_version_id",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint(
            "version_id",
            "structural_path",
            "ordinal",
            name="uq_document_chunks_structural_location",
        ),
    )
    op.create_index(
        "ix_document_chunks_page",
        "document_chunks",
        ["page"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_version_id",
        "document_chunks",
        ["version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_version_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_page", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(
        "ix_document_versions_ship_id", table_name="document_versions"
    )
    op.drop_index(
        "ix_document_versions_security_level",
        table_name="document_versions",
    )
    op.drop_index(
        "ix_document_versions_project_id", table_name="document_versions"
    )
    op.drop_index(
        "ix_document_versions_document_id", table_name="document_versions"
    )
    op.drop_index(
        "ix_document_versions_department", table_name="document_versions"
    )
    op.drop_table("document_versions")
    op.drop_table("documents")
