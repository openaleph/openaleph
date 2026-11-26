"""collection lakehouse uri

Revision ID: c5ecf5e2c35e
Revises: 575ded9400fd
Create Date: 2026-08-24 22:08:05.926699

"""

# revision identifiers, used by Alembic.
revision = "c5ecf5e2c35e"
down_revision = "575ded9400fd"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("collection", sa.Column("lakehouse_uri", sa.Unicode(), nullable=True))


def downgrade():
    op.drop_column("collection", "lakehouse_uri")
