"""collection maintenance flag

Revision ID: 747d728c53cc
Revises: c5ecf5e2c35e
Create Date: 2026-10-29 17:37:08.798223

"""

# revision identifiers, used by Alembic.
revision = "747d728c53cc"
down_revision = "c5ecf5e2c35e"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("collection", sa.Column("maintenance", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("collection", "maintenance")
