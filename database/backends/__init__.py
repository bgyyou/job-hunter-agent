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
    def insert_resume(self, data: Dict, *, user_id: str) -> str:
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
    def list_resumes(self, user_id: str) -> List[Dict]:
        """List all (non-deleted) resumes for a user, newest ``updated_at`` first."""

    @abstractmethod
    def soft_delete_resume(self, resume_id: str) -> None:
        """Mark a resume as deleted by setting ``deleted_at = now()``.

        Idempotent. Does not cascade to ``match_history`` (matches preserved as audit log).
        """

    # -------------------- JDs --------------------

    @abstractmethod
    def insert_jd(self, data: Dict, *, user_id: str) -> str:
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
    def list_jds(self, user_id: str, source: Optional[str] = None,
                 limit: int = 100) -> List[Dict]:
        """List recent JDs, optionally filtered by source (e.g. ``boss``, ``jobsdb``)."""

    @abstractmethod
    def get_jd_by_url(self, url: str, *, user_id: str) -> Optional[Dict]:
        """Lookup a JD by its source URL (the unique key for dedup)."""

    @abstractmethod
    def search_jds(self, keyword: str, industry_tag: Optional[str] = None,
                   function_tag: Optional[str] = None, position_tag: Optional[str] = None,
                   *, user_id: str, limit: int = 50) -> List[Dict]:
        """Keyword + tag search over title/company/raw_text. Substring match (LIKE)."""

    @abstractmethod
    def soft_delete_jd(self, jd_id: str) -> None:
        """Mark a JD as deleted. Cascades nothing; chunks/matches preserved."""

    @abstractmethod
    def update_jd_quality_score(self, jd_id: str, score: float,
                                checked_at: str) -> None:
        """Upsert ``jds.quality_score`` + ``quality_checked_at`` cache fields. v2.1 M11.

        Used by the JD quality scoring pipeline (see
        ``services.jd_quality_service.compute_jd_quality``) to persist the
        composite score after scoring. ``score`` is in [0, 1]; ``checked_at``
        is an ISO-8601 timestamp string.

        Idempotent: safe to call repeatedly. ``None`` should clear the cache.
        """

    @abstractmethod
    def update_jd_quality_score_cas(self, jd_id: str, score: float,
                                    checked_at: str,
                                    expected_checked_at: Optional[str]) -> bool:
        """M-v4-2 P1-001: 事务化 CAS 写 — 防止懒评分并发回写 race。

        同进程：``BEGIN IMMEDIATE`` 拿写锁，单 DB 文件写入串行化。
        跨进程：``WHERE quality_checked_at = expected`` 在 SQL 层
        挡掉任何绕过文件锁的并发写。

        Returns:
            True: 本调用真写了行（``rowcount > 0``）。
            False: ``quality_checked_at`` 已被别人改成其它值，写被 SQL 层拒。
            调用方二次 SELECT 拿别人刚算好的 score 即可。

        ``expected_checked_at=None`` 视为"未评分"（NULL），只有 DB 中
        ``quality_checked_at`` 仍为 NULL 时才会写入。
        """

    @abstractmethod
    def compute_or_get_jd_quality(
        self, jd_id: str,
        compute_fn: Any,  # Callable[[], Optional[float]]
    ) -> Optional[float]:
        """M-v4-2 P1-001: 同进程锁 + 跨进程 CAS 双层防并发 race 的懒评分。

        调用方传入 :class:`compute_fn`（无参返回 ``Optional[float]``）；后端负责：
        1. 拿同进程 ``threading.Lock``（按 jd_id 维度 — 不同 jd 不互锁）
        2. 锁内二次 ``SELECT quality_score FROM jds``；已存在直接返回
        3. 调 :class:`compute_fn`（LLM/heuristic 调用）
        4. ``update_jd_quality_score_cas`` 跨进程兜底

        Returns:
            最终的 ``quality_score``（可能是本调用算的，也可能是跨进程对手算的）。
            ``compute_fn`` 抛错 / 返 None → 返 None。
        """

    # -------------------- Matches --------------------

    @abstractmethod
    def insert_match(self, data: Dict, *, user_id: str) -> str:
        """Persist a resume↔JD match scoring run (M2 write-back).

        Required keys: ``resume_id``, ``jd_id``, ``score`` (0-100). Optional:
        ``matched_skills``, ``missing_skills``, ``rationale``, ``applied`` (default 0),
        ``user_feedback``, ``user_id``.
        """

    @abstractmethod
    def list_matches(self, resume_id: Optional[str] = None, jd_id: Optional[str] = None,
                     *, user_id: str, limit: int = 100) -> List[Dict]:
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
    def insert_optimization(self, data: Dict, *, user_id: str) -> str:
        """Save one LLM-generated optimization suggestion (one row per suggestion).

        Required: ``jd_id``, ``section`` (e.g. ``'skills'``), ``original_content``,
        ``suggested_content``. Optional: ``reason``, ``chunk_id``, ``user_adopted``,
        ``user_rating`` (1-5), ``user_id``.
        """

    @abstractmethod
    def list_optimizations(self, jd_id: Optional[str] = None,
                           *, user_id: str) -> List[Dict]:
        """List optimization suggestions, optionally for a specific JD."""

    @abstractmethod
    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        """Toggle the ``user_adopted`` flag (1=accepted, 0=rejected). v2.1 M2."""

    # -------------------- Knowledge Chunks (RAG) --------------------

    @abstractmethod
    def insert_chunk(self, data: Dict, *, user_id: str) -> str:
        """Insert a single semantic chunk + embedding for a JD.

        Required: ``jd_id``, ``content``, ``chunk_type`` (one of
        ``overview``/``responsibility``/``requirement``/``nice_to_have``/``full``).
        Optional: ``heading_path``, ``embedding`` (List[float], 512-dim BGE),
        ``order_index``.
        """

    @abstractmethod
    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict], *, user_id: str) -> List[str]:
        """Bulk-insert chunks for a JD in one transaction. Returns chunk ids in order."""

    @abstractmethod
    def get_chunks_by_jd(self, jd_id: str) -> List[Dict]:
        """All chunks for a given JD, ordered by ``order_index`` ASC."""

    # -------------------- Quality Checks (Observability) --------------------

    @abstractmethod
    def insert_quality_check(self, data: Dict, *, user_id: str) -> int:
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

    # -------------------- Skeleton Cache --------------------

    @abstractmethod
    def get_skeleton_cache(self, position: str, industry: str,
                           function: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return cached skeleton if not expired; otherwise ``None``.

        The returned dict mirrors ``build_skeleton`` output:
        ``{"text": str, "source": str, "n_chunks": int, "industries_covered": List[str]}``.
        """

    @abstractmethod
    def set_skeleton_cache(self, position: str, industry: str,
                           skeleton: Dict[str, Any],
                           function: Optional[str] = None,
                           ttl_hours: int = 24) -> None:
        """Upsert a skeleton cache entry with the given TTL."""

    # -------------------- LLM Observability --------------------

    @abstractmethod
    def insert_llm_call(self, data: Dict[str, Any], *, user_id: str) -> int:
        """Append one LLM invocation observability record.

        Required: ``model``, ``operation``. Optional: ``request_id``,
        ``endpoint``, ``prompt_tokens``, ``completion_tokens``, ``total_tokens``,
        ``latency_ms``, ``status`` (``'success'``/``'error'``/``'cache_hit'``),
        ``error_type``, ``error_message``, ``metadata`` (Dict),
        ``user_id`` (default ``'default'``, v4 T1.4 配额统计维度).

        Returns the autoincrement integer id.
        """

    @abstractmethod
    def get_llm_usage_today(self, user_id: Optional[str] = None) -> Dict[str, int]:
        """当天 LLM 用量汇总：``{"calls": int, "tokens": int}``。

        ``user_id`` 为 ``None`` 时统计全局（所有用户），否则只统计该用户。
        当天口径：SQLite ``date(created_at) = date('now')``，
        PG ``created_at::date = CURRENT_DATE``。
        """

    @abstractmethod
    def list_llm_calls(self, model: Optional[str] = None,
                       operation: Optional[str] = None,
                       status: Optional[str] = None,
                       limit: int = 100) -> List[Dict]:
        """List recent LLM call records, newest first; filter by model/operation/status."""

    # -------------------- Flow A Drafts --------------------

    @abstractmethod
    def upsert_flow_a_draft(self, data: Dict[str, Any], *, user_id: str) -> str:
        """Create or update a recoverable Flow A draft.

        JSON fields: ``section_data``, ``section_messages``, ``section_status``,
        ``generation_state``. Returns the draft id.
        """

    @abstractmethod
    def get_flow_a_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one non-deleted Flow A draft with JSON columns parsed."""

    @abstractmethod
    def get_latest_flow_a_draft(self, user_id: str,
                                statuses: Optional[tuple[str, ...]] = None) -> Optional[Dict[str, Any]]:
        """Fetch the latest recoverable Flow A draft for a user."""

    @abstractmethod
    def abandon_flow_a_draft(self, draft_id: str) -> None:
        """Mark a Flow A draft as abandoned so it is no longer recoverable."""

    # -------------------- Audit Logs --------------------

    @abstractmethod
    def insert_audit_log(self, data: Dict, *, user_id: str) -> int:
        """Append one user action audit event (login / resume CRUD / JD upload / etc.).

        Required: ``action`` (e.g. ``'user.login.success'``). Optional: ``user_id``
        (default ``'default'``), ``target_table``, ``target_id``, ``status``
        (``'success'``/``'failure'``, default ``'success'``), ``error_message``,
        ``details`` (Dict, JSON-serialized).

        Returns the autoincrement integer id.
        """

    @abstractmethod
    def list_audit_logs(self, user_id: Optional[str] = None,
                        action: Optional[str] = None,
                        target_table: Optional[str] = None,
                        limit: int = 100) -> List[Dict]:
        """List recent audit logs, newest first; filter by user / action / target_table."""

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
                      user_id: Optional[str] = None,
                      filter_position: Optional[str] = None) -> List[Dict]:
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
            filter_position: Hard filter on the parent JD's ``position_tag``
                (e.g. only chunks from "产品经理" JDs across all industries).

        Returns:
            List of dicts with ``chunk_id``, ``jd_id``, ``chunk_text``,
            ``chunk_type``, ``context``, ``heading_path``, ``similarity`` (0-1),
            and ``jd_industry_tag`` so the service layer can apply industry boost.
        """

    @abstractmethod
    def like_search_chunks(self, query_text: str, top_k: int = 5,
                           filter_chunk_type: Optional[str] = None,
                           user_id: Optional[str] = None,
                           filter_position: Optional[str] = None) -> List[Dict]:
        """LIKE-based fallback when no embedder is available.

        Returns the same shape as ``vector_search`` but with ``similarity=0.0``.
        Used by ``RetrievalService`` when ``Embedder`` fails to load.
        """

    # -------------------- v3 M-rebuild-1: Structured JDs --------------------

    @abstractmethod
    def insert_jd_structured(self, data: Dict, *, user_id: str) -> int:
        """Insert one structured JD record.

        Required: ``source`` (``'text'``/``'image'``/``'rag'``). Optional:
        ``user_id``, ``raw_text``, ``company``, ``title``, ``industry``,
        ``function``, ``level``, ``responsibilities`` (List[str]),
        ``requirements`` (List[str]).

        Returns the autoincrement ``jd_id`` (int).
        """

    @abstractmethod
    def get_jd_structured(self, jd_id: int) -> Optional[Dict]:
        """Fetch one structured JD by id; returns None if missing/soft-deleted."""

    @abstractmethod
    def list_jds_structured(self, user_id: str,
                            source: Optional[str] = None,
                            limit: int = 100) -> List[Dict]:
        """List recent structured JDs, optionally filtered by source."""

    # -------------------- v3 M-rebuild-2: Rewrite History --------------------

    @abstractmethod
    def insert_rewrite_history(self, data: Dict, *, user_id: str) -> int:
        """Persist one rewrite run (mode A/B/A+B).

        Required: ``resume_id``, ``mode``. Optional: ``user_id``, ``jd_id``,
        ``input_snapshot`` (Dict), ``output_snapshot`` (Dict),
        ``rewrite_notes`` (Dict), ``user_edited`` (0/1).

        Returns the autoincrement ``rewrite_id``.
        """

    @abstractmethod
    def list_rewrite_history(self, resume_id: Optional[str] = None,
                             *, user_id: str,
                             limit: int = 100) -> List[Dict]:
        """List recent rewrites, optionally filtered by resume."""

    @abstractmethod
    def mark_rewrite_user_edited(self, rewrite_id: int) -> None:
        """Mark a rewrite as user-edited (sets ``user_edited = 1``)."""

    # -------------------- v3 M-rebuild-1: Resume Achievements --------------------

    @abstractmethod
    def update_resume_achievements(self, resume_id: str, achievements: List[str]) -> None:
        """Update the top-level ``resumes.achievements`` JSON column."""
