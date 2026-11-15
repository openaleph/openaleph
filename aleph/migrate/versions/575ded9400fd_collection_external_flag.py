"""collection external flag

Revision ID: 575ded9400fd
Revises: 48e003f89633
Create Date: 2026-02-18 22:18:57.453364

"""

# revision identifiers, used by Alembic.
revision = "575ded9400fd"
down_revision = "48e003f89633"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("collection", sa.Column("external", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("collection", "external")
