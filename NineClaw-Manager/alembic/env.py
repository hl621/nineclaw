"""Alembic environment configuration for async SQLModel migrations."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlmodel import SQLModel

# Import all models to ensure they are registered with SQLModel.metadata
from app.models import (
    Tenant,
    ServiceTemplate,
    ServiceInstance,
    ServiceGroup,
    ReconcileLog,
    Provider,
    Workflow,
    WorkflowVersion,
    WorkflowRun,
    WorkflowScopeRun,
    WorkflowNodeRun,
    WorkflowEdgeRun,
    WorkflowNodeAttempt,
    WorkflowNodeTypeDefinition,
    WorkflowJob,
    WorkflowEvent,
    WorkflowArtifact,
)
from app.core.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with the value from settings
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = SQLModel.metadata

_MIGRATION_LOCK_NAME = "nineclaw-manager:alembic-migrations"
_ACQUIRE_MIGRATION_LOCK = text("SELECT pg_advisory_lock(hashtext(:lock_name))")
_RELEASE_MIGRATION_LOCK = text("SELECT pg_advisory_unlock(hashtext(:lock_name))")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with the given connection."""
    if connection.in_transaction():
        raise RuntimeError("Alembic migrations require a fresh database connection")
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )

    lock_acquired = False
    migration_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        if connection.dialect.name == "postgresql":
            connection.execute(
                _ACQUIRE_MIGRATION_LOCK, {"lock_name": _MIGRATION_LOCK_NAME}
            )
            lock_acquired = True
        with context.begin_transaction():
            context.run_migrations()
    except BaseException as error:
        migration_error = error
        raise
    finally:
        if lock_acquired:
            try:
                if connection.in_transaction():
                    if migration_error is None:
                        connection.commit()
                    else:
                        connection.rollback()
            except BaseException as error:
                cleanup_error = error
            try:
                connection.execute(
                    _RELEASE_MIGRATION_LOCK, {"lock_name": _MIGRATION_LOCK_NAME}
                )
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
            if cleanup_error is not None and migration_error is None:
                raise cleanup_error


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with sync engine."""
    from sqlalchemy import create_engine

    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
