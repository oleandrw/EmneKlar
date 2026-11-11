"""Emneforside is removed: drop its draft table

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06 21:00:00

Emneforside (the homepage builder) is replaced by Emnedesign, which styles the existing front page together with
the rest of the course. ``homepage_drafts`` held only local drafts that were never sent to Canvas; pages created
or replaced from them in Canvas, and their backups and change-log entries, are untouched. The database is copied
to ``backups\\database`` before every migration, so old drafts can still be recovered from that copy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('homepage_drafts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_homepage_drafts_course_id'))
    op.drop_table('homepage_drafts')


def downgrade() -> None:
    op.create_table(
        'homepage_drafts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('course_id', sa.String(length=32), nullable=False),
        sa.Column('mode', sa.String(length=24), nullable=False),
        sa.Column('style', sa.String(length=24), nullable=False),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('notes', sa.JSON(), nullable=False),
        sa.Column('ai_used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('homepage_drafts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_homepage_drafts_course_id'), ['course_id'], unique=False)
