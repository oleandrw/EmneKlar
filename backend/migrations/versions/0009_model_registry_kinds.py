"""One model registry for every kind of AI model

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-27 19:00:00

``ai_models`` becomes the one source of truth for AI models: image generation, transcription and embedding models are
rows next to the text models, instead of lists in separate files.

* ``kind``: text | image | transcription | embedding.
* ``params``: the request parameters the model supports (image qualities, sizes, reference images …).
* ``priority`` and ``is_default``: the teacher's own preference in automatic choices.
* ``description``: a short text shown in model selectors.

Models that were added earlier (by hand or from a provider's model list) were all stored as text models. Those whose
name belongs to a family that is not a text model get the right kind once, here, so that they stop being offered for
text tasks and show up where they belong; the teacher can change the type afterwards. Nothing is enabled, disabled or
deleted, and the names stored with earlier results (illustrations, the usage log) are untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

#: SQL LIKE patterns (lower-case model id) → kind. The same families as ``kind_hints`` in model_catalog.json at the
#: time of this migration; kept here so the migration does not change when the catalog does.
FAMILIES = (("gpt-image-%", "image"), ("dall-e-%", "image"), ("%transcribe%", "transcription"),
            ("whisper%", "transcription"), ("%embedding%", "embedding"))


def upgrade() -> None:
    with op.batch_alter_table('ai_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=16), nullable=False, server_default='text'))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('params', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'))
    models = sa.table('ai_models', sa.column('model_id', sa.String), sa.column('kind', sa.String),
                      sa.column('text', sa.Boolean), sa.column('vision', sa.Boolean),
                      sa.column('structured_output', sa.Boolean))
    for pattern, kind in FAMILIES:
        op.execute(models.update().where(sa.func.lower(models.c.model_id).like(pattern), models.c.kind == 'text')
                   .values(kind=kind, text=False, vision=False, structured_output=False))


def downgrade() -> None:
    with op.batch_alter_table('ai_models', schema=None) as batch_op:
        batch_op.drop_column('is_default')
        batch_op.drop_column('priority')
        batch_op.drop_column('params')
        batch_op.drop_column('description')
        batch_op.drop_column('kind')
