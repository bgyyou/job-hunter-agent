"""Service layer.

Business logic that used to be embedded in `database/backends/*` lives here.
Backends own pure CRUD + dialect adapters; services orchestrate domain flows
(vector retrieval, PDF ingestion, …) on top of those primitives.
"""
