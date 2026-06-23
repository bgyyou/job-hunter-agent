"""Job Hunter v2 database package."""

from database.factory import get_db
from database.backends.sqlite_backend import SqliteBackend

__all__ = ["get_db", "SqliteBackend"]
