"""xref judgement graph: xref_edge + xref_cluster (see xref-resolver-sql.md)

Revision ID: d9a841b3de0f
Revises: 575ded9400fd
Create Date: 2026-07-16 16:23:25.113700

"""

# revision identifiers, used by Alembic.
revision = "d9a841b3de0f"
down_revision = "575ded9400fd"

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade():
    op.create_table(
        "xref_cluster",
        sa.Column("entity_id", sa.Unicode(length=512), nullable=False),
        sa.Column("canonical_id", sa.Unicode(length=512), nullable=False),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    op.create_index(
        op.f("ix_xref_cluster_canonical_id"),
        "xref_cluster",
        ["canonical_id"],
        unique=False,
    )
    op.create_table(
        "xref_edge",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("target", sa.Unicode(length=512), nullable=False),
        sa.Column("source", sa.Unicode(length=512), nullable=False),
        sa.Column("judgement", sa.Unicode(length=14), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("user", sa.Unicode(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_collection_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "target_collection_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_xref_edge_created_live",
        "xref_edge",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_xref_edge_pair_live",
        "xref_edge",
        ["source", "target"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_xref_edge_source_colls",
        "xref_edge",
        ["source_collection_ids"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_xref_edge_source_live",
        "xref_edge",
        ["source"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_xref_edge_target_colls",
        "xref_edge",
        ["target_collection_ids"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_xref_edge_target_live",
        "xref_edge",
        ["target"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    op.drop_index(
        "ix_xref_edge_target_live",
        table_name="xref_edge",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_xref_edge_target_colls", table_name="xref_edge", postgresql_using="gin"
    )
    op.drop_index(
        "ix_xref_edge_source_live",
        table_name="xref_edge",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_xref_edge_source_colls", table_name="xref_edge", postgresql_using="gin"
    )
    op.drop_index(
        "ix_xref_edge_pair_live",
        table_name="xref_edge",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_xref_edge_created_live",
        table_name="xref_edge",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("xref_edge")
    op.drop_index(op.f("ix_xref_cluster_canonical_id"), table_name="xref_cluster")
    op.drop_table("xref_cluster")
