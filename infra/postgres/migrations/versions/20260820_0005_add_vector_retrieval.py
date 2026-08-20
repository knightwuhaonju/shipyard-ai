"""add deterministic vector retrieval storage

Revision ID: 20260820_0005
Revises: 20260820_0004
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "20260820_0005"
down_revision: str | Sequence[str] | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_chunk_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(8), nullable=False),
        sa.CheckConstraint(
            "btrim(embedding_model) <> ''",
            name="ck_document_chunk_embeddings_model",
        ),
        sa.CheckConstraint(
            "vector_norm(embedding) > 0",
            name="ck_document_chunk_embeddings_nonzero",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.chunk_id"],
            name="fk_document_chunk_embeddings_chunk_id",
        ),
        sa.PrimaryKeyConstraint("chunk_id", "embedding_model"),
    )
    op.create_index(
        "ix_document_chunk_embeddings_model",
        "document_chunk_embeddings",
        ["embedding_model"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunk_embeddings_hnsw_cosine",
        "document_chunk_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunk_embeddings_hnsw_cosine",
        table_name="document_chunk_embeddings",
    )
    op.drop_index(
        "ix_document_chunk_embeddings_model",
        table_name="document_chunk_embeddings",
    )
    op.drop_table("document_chunk_embeddings")
