from alembic import context
from sqlalchemy import engine_from_config, pool

from aleph.model import db

config = context.config
config.set_main_option("script_location", ".")
target_metadata = db.metadata


def ignore_autogen(obj, name, type_, reflexted, compare_to):
    if type_ == "table" and name.startswith("tabular_"):
        return False
    return True


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    # Aleph requires PostgreSQL, fail if not
    if not url or "postgres" not in url:
        raise RuntimeError("aleph database must be PostgreSQL!")
    # Convert postgresql:// to postgresql+psycopg:// to use psycopg3
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    context.configure(url=url, include_object=ignore_autogen)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    config_section = config.get_section(config.config_ini_section) or {}

    # Ensure PostgreSQL and convert to use psycopg3
    url_key = "sqlalchemy.url"
    if url_key in config_section:
        url = config_section[url_key]
        if not url or "postgres" not in url:
            raise RuntimeError("aleph database must be PostgreSQL!")
        # Convert postgresql:// to postgresql+psycopg:// to use psycopg3
        config_section[url_key] = url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    engine = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    connection = engine.connect()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=ignore_autogen,
    )

    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
