"""Alembic environment. Used both by the app at start-up and by the alembic CLI."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from emneklar.core.storage.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "")
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
