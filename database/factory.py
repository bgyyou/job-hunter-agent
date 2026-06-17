"""Factory function to create the appropriate database backend."""

import os

from database.backends.sqlite_backend import SqliteBackend


def get_db() -> SqliteBackend:
    """
    Return the appropriate database backend instance.

    - DATABASE_URL starts with 'postgresql://' → PostgresBackend(db_url)
    - DATABASE_URL starts with 'sqlite://' → SqliteBackend()
    - DATABASE_URL unset or empty → SqliteBackend() (default: data/jobhunter_v2.db)
    """
    db_url = os.environ.get("DATABASE_URL", "")

    if db_url.startswith("postgresql://"):
        from database.backends.postgres_backend import PostgresBackend
        return PostgresBackend(db_url)

    # sqlite:// or unset → SQLite
    return SqliteBackend()
