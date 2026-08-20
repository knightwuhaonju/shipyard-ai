"""add lexical retrieval metadata and indexes

Revision ID: 20260820_0004
Revises: 20260819_0003
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260820_0004"
down_revision: str | Sequence[str] | None = "20260819_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNMAPPABLE_DOCUMENT_TYPE = (
    "cannot infer document_type for existing document version"
)


def _fail_if_document_type_is_unmappable() -> None:
    if context.is_offline_mode():
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM document_versions WHERE document_type IS NULL
                  ) THEN
                    RAISE EXCEPTION
                      'cannot infer document_type for existing document version';
                  END IF;
                END
                $$
                """
            )
        )
        return

    has_unmappable_row = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM document_versions WHERE document_type IS NULL"
            ")"
        )
    )
    if has_unmappable_row:
        raise RuntimeError(_UNMAPPABLE_DOCUMENT_TYPE)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "document_versions",
        sa.Column("document_type", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE document_versions
        SET document_type = CASE
          WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\\.pdf$' THEN 'pdf'
          WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\\.docx$' THEN 'docx'
          WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\\.xlsx$' THEN 'xlsx'
          WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\\.txt$' THEN 'txt'
          WHEN regexp_replace(lower(source_uri), '[?#].*$', '') ~ '\\.(md|markdown)$'
            THEN 'markdown'
          ELSE NULL
        END
        """
    )
    _fail_if_document_type_is_unmappable()
    op.alter_column("document_versions", "document_type", nullable=False)
    op.create_check_constraint(
        "ck_document_versions_document_type",
        "document_versions",
        "document_type IN ('pdf', 'docx', 'xlsx', 'txt', 'markdown')",
    )
    op.create_index(
        "ix_document_versions_document_type",
        "document_versions",
        ["document_type"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_lexical_tsv",
        "document_chunks",
        [sa.text("to_tsvector('simple'::regconfig, normalized_text)")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_chunks_normalized_text_trgm",
        "document_chunks",
        ["normalized_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_normalized_text_trgm",
        table_name="document_chunks",
    )
    op.drop_index(
        "ix_document_chunks_lexical_tsv",
        table_name="document_chunks",
    )
    op.drop_index(
        "ix_document_versions_document_type",
        table_name="document_versions",
    )
    op.drop_constraint(
        "ck_document_versions_document_type",
        "document_versions",
        type_="check",
    )
    op.drop_column("document_versions", "document_type")
