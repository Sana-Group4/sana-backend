from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os

import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool

# Alembic config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Make project root importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import models so Base.metadata is populated
from db import Base
import models  # noqa: F401

# Metadata is not none
target_metadata = Base.metadata


def get_sync_url(async_url: str) -> str:
    """Convert async database URL to sync for Alembic."""
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    # url = config.get_main_option("sqlalchemy.url")
    url = get_sync_url(os.getenv("DATABASE_URL"))
    context.configure(
        url=url,
        target_metadata=target_metadata, 
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        get_sync_url(os.getenv("DATABASE_URL")),
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata, 
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
