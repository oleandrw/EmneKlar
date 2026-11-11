"""Remove the Dry run switch (stored setting and change-log column) and add the alt-text suggestion queue

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06 10:00:00

* ``settings.app.dry_run`` is removed from the stored settings (the model ignores it anyway).
* ``change_log.dry_run`` is dropped. Entries written while Dry run was on keep ``action = 'dry_run'``, so the
  history stays readable – nothing in the log is deleted.
* ``alt_text_suggestions``: KI-forslag til alt-tekst prepared ahead of review, reused while unchanged.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def _drop_stored_dry_run() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT value FROM settings WHERE key = 'app'")).fetchone()
    if row is None or row[0] is None:
        return
    value = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    if isinstance(value, dict) and "dry_run" in value:
        value.pop("dry_run")
        bind.execute(sa.text("UPDATE settings SET value = :value WHERE key = 'app'"),
                     {"value": json.dumps(value, ensure_ascii=False)})


def upgrade() -> None:
    _drop_stored_dry_run()
    with op.batch_alter_table('change_log', schema=None) as batch_op:
        batch_op.drop_column('dry_run')
    op.create_table(
        'alt_text_suggestions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('course_id', sa.String(length=32), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('finding_id', sa.Integer(), nullable=True),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('suggestion', sa.Text(), nullable=False),
        sa.Column('decorative', sa.Boolean(), nullable=False),
        sa.Column('image_kind', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.String(length=8), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('model', sa.String(length=200), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'fingerprint', name='uq_alt_text_suggestions_finding'),
    )
    with op.batch_alter_table('alt_text_suggestions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alt_text_suggestions_course_id'), ['course_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('alt_text_suggestions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alt_text_suggestions_course_id'))
    op.drop_table('alt_text_suggestions')
    with op.batch_alter_table('change_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False))
