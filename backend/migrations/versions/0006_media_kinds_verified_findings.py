"""Media kinds chosen by the teacher and «verified» findings

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06 15:00:00

* ``media_assessments``: what a recording is (audio only, video with sound, video without sound), per course and
  media. The accessibility requirement depends on it (WCAG 1.2.1 or 1.2.2).
* ``finding_decisions.reason``: for the new decision «verified» (the teacher confirmed what a manual check asks for),
  the confirmation chosen from the rule. Existing «ignored» decisions are unchanged.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('finding_decisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reason', sa.String(length=32), nullable=True))
    op.create_table(
        'media_assessments',
        sa.Column('course_id', sa.String(length=32), nullable=False),
        sa.Column('media_key', sa.String(length=400), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('course_id', 'media_key'),
    )


def downgrade() -> None:
    op.drop_table('media_assessments')
    with op.batch_alter_table('finding_decisions', schema=None) as batch_op:
        batch_op.drop_column('reason')
