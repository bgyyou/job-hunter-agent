"""Abstract base class for all database backends.

The contract here is the single source of truth for both `SQLiteBackend` and
`PostgresBackend`. Implementations should NOT duplicate the docstrings; users
calling `help(backend.insert_resume)` will see this docstring through MRO.

All methods are sync (no async) and follow these conventions:

- **Inputs**: dicts with snake_case keys matching schema columns.
- **Outputs**: `insert_*` returns the new id (str/int), `get_*` returns Optional[Dict],
  `list_*` returns List[Dict] sorted newest-first, `update_*` returns None.
- **Soft delete**: rows with `deleted_at IS NOT NULL` are excluded from all reads.
- **JSON columns**: lists/dicts are stored as JSON strings; reads return parsed Python.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseBackend(ABC):
    """Abstract storage contract for resumes / JDs / matches / chunks / etc.

    Concrete backends (`SQLiteBackend`, `PostgresBackend`) must implement every
    method here. Use `database.factory.get_db()` to obtain the configured
    backend rather than instantiating directly.
    """

    # -------------------- Resumes --------------------

    @abstractmethod
    def insert_resume(self, data: Dict) -> str:
        """Insert or upsert a resume profile.

        Args:
            data: Dict with keys ``id`` (optional, generated if missing),
                ``user_id``, ``name``, ``phone``, ``email``, ``summary``,
                ``skills`` (List[str]), ``experience_years``, ``domains``,
                ``target_roles``, ``preferred_locations``, ``education``,
                ``projects``.

        Returns:
            The resume id (uuid string).
        """

    @abstractmethod
    def get_resume(self, resume_id: str) -> Optional[Dict]:
        """Fetch a single resume by id. JSON columns are parsed back to Python.

        Returns ``None`` if the resume does not exist or has been soft-deleted.
        """

    @abstractmethod
    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        """List all (non-deleted) resumes for a user, newest ``updated_at`` first."""

    @abstractmethod
    def soft_delete_resume(self, resume_id: str) -> None:
        """Mark a resume as deleted by setting ``deleted_at = now()``.

        Idempotent. Does not cascade to ``match_history`` (matches preserved as audit log).
        """

    # -------------------- JDs --------------------

    @abstractmethod
    def insert_jd(self, data: Dict) -> str:
        """Insert or upsert a JD by ``url`` (unique key).

        Required keys: ``url``, ``title``. Optional: ``company``, ``location``,
        ``salary_*``, ``industry_tag``, ``function_tag``, ``position_tag``,
        ``raw_text``, ``source``, ``user_id``.

        Returns the JD id (uuid string).
        """

    @abstractmethod
    def get_jd(self, jd_id: str) -> Optional[Dict]:
        """Fetch a JD by id; returns ``None`` if missing or soft-deleted."""

    @abstractmethod
    def list_jds(self, user_id: str = "default", source: Optional[str] = None,
                 limit: int = 100) -> List[Dict]:
        """List recent JDs, optionally filtered by source (e.g. ``boss``, ``jobsdb``)."""

    @abstractmethod
    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        """Lookup a JD by its source URL (the unique key for dedup)."""

    @abstractmethod
    def search_jds(self, keyword: str, industry_tag: Optional[str] = None,
                   function_tag: Optional[str] = None, position_tag: Optional[str] = None,
                   user_id: str = "default", limit: int = 50) -> List[Dict]:
        """Keyword + tag search over title/company/raw_text. Substring match (LIKE)."""

    @abstractmethod
    def soft_delete_jd(self, jd_id: str) -> None:
        """Mark a JD as deleted. Cascades nothing; chunks/matches preserved."""

    # -------------------- Matches --------------------

    @abstractmethod
    def insert_match(self, data: Dict) -> str:
        """Persist a resume↔JD match scoring run (M2 write-back).

        Required keys: ``resume_id``, ``jd_id``, ``score`` (0-100). Optional:
        ``matched_skills``, ``missing_skills``, ``rationale``, ``applied`` (default 0),
        ``user_feedback``, ``user_id``.
        """

    @abstractmethod
    def list_matches(self, resume_id: Optional[str] = None, jd_id: Optional[str] = None,
                     user_id: str = "default", limit: int = 100) -> List[Dict]:
        """List match records, optionally filtered by resume or JD, newest first."""

    @abstractmethod
    def update_match_applied(self, match_id: str, applied: int,
                             applied_at: Optional[str] = None) -> None:
        """Mark a match as applied (1) / un-applied (0). v2.1 M2.

        ``applied_at`` defaults to ``now()`` when ``applied=1`` and not provided.
        """

    @abstractmethod
    def update_match_feedback(self, match_id: str, feedback: str) -> None:
        """Update ``user_feedback`` enum: ``'read'`` / ``'rejected'`` / ``'accepted'``. v2.1 M2."""

    # -------------------- Optimizations --------------------

    @abstractmethod
    def insert_optimization(self, data: Dict) -> str:
        """Save one LLM-generated optimization suggestion (one row per suggestion).

        Required: ``jd_id``, ``section`` (e.g. ``'skills'``), ``original_content``,
        ``suggested_content``. Optional: ``reason``, ``chunk_id``, ``user_adopted``,
        ``user_rating`` (1-5), ``user_id``.
        """

    @abstractmethod
    def list_optimizations(self, jd_id: Optional[str] = None,
                           user_id: str = "default") -> List[Dict]:
        """List optimization suggestions, optionally for a specific JD."""

    @abstractmethod
    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        """Toggle the ``user_adopted`` flag (1=accepted, 0=rejected). v2.1 M2."""

    # -------------------- Knowledge Chunks (RAG) --------------------

    @abstractmethod
    def insert_chunk(self, data: Dict) -> str:
        """Insert a single semantic chunk + embedding for a JD.

        Required: ``jd_id``, ``content``, ``chunk_type`` (one of
        ``overview``/``responsibility``/``requirement``/``nice_to_have``/``full``).
        Optional: ``heading_path``, ``embedding`` (List[float], 512-dim BGE),
        ``order_index``.
        """

    @abstractmethod
    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict]) -> List[str]:
        """Bulk-insert chunks for a JD in one transaction. Returns chunk ids in order."""

    @abstractmethod
    def get_chunks_by_jd(self, jd_id: str) -> List[Dict]:
        """All chunks for a given JD, ordered by ``order_index`` ASC."""

    # -------------------- Quality Checks (Observability) --------------------

    @abstractmethod
    def insert_quality_check(self, data: Dict) -> int:
        """Append one observability event (LLM call latency, scoring deviation, etc.).

        Required: ``check_type`` (e.g. ``'llm_call'``), ``target_table``, ``score``.
        Optional: ``target_id``, ``details`` (Dict, JSON-serialized), ``user_id``.

        Returns the autoincrement integer id.
        """

    @abstractmethod
    def list_quality_checks(self, check_type: Optional[str] = None,
                            target_table: Optional[str] = None,
                            limit: int = 100) -> List[Dict]:
        """List recent quality_check rows, newest first; filter by type/target_table."""

    # -------------------- Aggregates --------------------

    @abstractmethod
    def get_stats(self) -> Dict:
        """Return per-table row counts for the dashboard.

        Keys: ``resumes``, ``jds``, ``matches``, ``optimizations``, ``chunks``,
        ``quality_checks``. All counts exclude soft-deleted rows.
        """

    @abstractmethod
    def vector_search(self, query_embedding: List[float], top_k: int = 5,
                      filter_chunk_type: Optional[str] = None,
                      user_id: Optional[str] = None) -> List[Dict]:
        """Pure vector cosine search over knowledge_chunks (dialect-specific).

        No chunk_type weighting, no min_similarity filtering — those live in
        ``services.retrieval_service.RetrievalService``. This method is the
        thin dialect adapter: PG uses pgvector ``<=>``; SQLite computes cosine
        in-process with numpy.

        Args:
            query_embedding: Pre-computed query vector (caller embeds).
            top_k: Number of raw candidates to return (caller usually over-fetches).
            filter_chunk_type: Restrict to one of overview/responsibility/...
            user_id: Restrict to chunks linked to JDs owned by this user.

        Returns:
            List of dicts with ``chunk_id``, ``jd_id``, ``chunk_text``,
            ``chunk_type``, ``context``, ``heading_path``, ``similarity`` (0-1).
        """

    @abstractmethod
    def like_search_chunks(self, query_text: str, top_k: int = 5,
                           filter_chunk_type: Optional[str] = None,
                           user_id: Optional[str] = None) -> List[Dict]:
        """LIKE-based fallback when no embedder is available.

        Returns the same shape as ``vector_search`` but with ``similarity=0.0``.
        Used by ``RetrievalService`` when ``Embedder`` fails to load.
        """
