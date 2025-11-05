"""Create endpoint_challenge table

Revision ID: eb68f277ab61
Revises:
Create Date: 2025-11-04 15:31:00.000000

"""
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "eb68f277ab61"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op=None):
    op.create_table(
        "endpoint_challenge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("docker_image", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"],
            ["challenges.id"],
            name="fk_endpoint_challenge_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade(op=None):
    op.drop_table("endpoint_challenge")
