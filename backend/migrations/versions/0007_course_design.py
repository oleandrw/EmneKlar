"""Emnedesign: the course's design choice and content kept out of it

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06 18:00:00

* ``course_designs``: the design profile and version a course chose, and the treatment (keep the structure or a
  suggested structure). Saving it changes no content.
* ``course_design_exclusions``: content marked «Behold eksisterende design».
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'course_designs',
        sa.Column('course_id', sa.String(length=32), nullable=False),
        sa.Column('profile_id', sa.String(length=40), nullable=False),
        sa.Column('profile_version', sa.String(length=16), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('illustrations', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('course_id'),
    )
    op.create_table(
        'course_design_exclusions',
        sa.Column('course_id', sa.String(length=32), nullable=False),
        sa.Column('item_key', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('course_id', 'item_key'),
    )


def downgrade() -> None:
    op.drop_table('course_design_exclusions')
    op.drop_table('course_designs')
