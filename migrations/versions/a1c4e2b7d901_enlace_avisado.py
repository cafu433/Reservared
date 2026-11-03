"""El último enlace de sesión que se le envió al paciente

Revision ID: a1c4e2b7d901
Revises: 66ce9b46780b
Create Date: 2026-11-03 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "a1c4e2b7d901"
down_revision = "66ce9b46780b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("cita") as t:
        t.add_column(sa.Column("enlace_avisado", sa.String(length=500), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("cita") as t:
        t.drop_column("enlace_avisado")
