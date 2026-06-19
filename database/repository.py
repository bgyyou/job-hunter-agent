"""Unified database access layer for Job Hunter v2."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger


class JobHunterDB:
    """Central database access class. Manages data/jobhunter_v2.db."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent / "data" / "jobhunter_v2.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        schema_path = Path(__file__).parent.parent / "data" / "schema.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
        logger.info(f"Database initialized: {self.db_path}")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        return dict(row) if row else None

    def _json_serialize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _json_deserialize(self, value: Optional[str]) -> Any:
        if value is None:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _embedding_to_blob(embedding) -> Optional[bytes]:
        """Serialize an embedding (list/tuple/bytes) to a JSON-encoded BLOB.

        SQLite cannot bind raw Python lists; v2.1 SqliteBackend stores the
        JSON bytes and decodes on read. The facade mirrors that contract so
        callers that still hit JobHunterDB don't silently corrupt vectors.
        """
        if embedding is None:
            return None
        if isinstance(embedding, (bytes, bytearray)):
            return bytes(embedding)
        try:
            return json.dumps(list(embedding)).encode("utf-8")
        except (TypeError, ValueError):
            return None

    # ================================================================
    # Resumes
    # ================================================================

    def insert_resume(self, data: Dict) -> str:
        resume_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO resumes
                   (id, user_id, name, phone, email, summary, skills,
                    experience_years, domains, target_roles, preferred_locations,
                    education, projects, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resume_id,
                    data.get("user_id", "default"),
                    data.get("name", ""),
                    data.get("phone"),
                    data.get("email"),
                    data.get("summary"),
                    self._json_serialize(data.get("skills", [])),
                    data.get("experience_years", 0),
                    self._json_serialize(data.get("domains", [])),
                    self._json_serialize(data.get("target_roles", [])),
                    self._json_serialize(data.get("preferred_locations", [])),
                    self._json_serialize(data.get("education", [])),
                    self._json_serialize(data.get("projects", [])),
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return resume_id

    def get_resume(self, resume_id: str) -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM resumes WHERE id = ? AND deleted_at IS NULL", (resume_id,)
            ).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            d["skills"] = self._json_deserialize(d["skills"])
            d["domains"] = self._json_deserialize(d["domains"])
            d["target_roles"] = self._json_deserialize(d["target_roles"])
            d["preferred_locations"] = self._json_deserialize(d["preferred_locations"])
            d["education"] = self._json_deserialize(d["education"])
            d["projects"] = self._json_deserialize(d["projects"])
            return d
        finally:
            conn.close()

    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM resumes WHERE user_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["skills"] = self._json_deserialize(d["skills"])
                d["domains"] = self._json_deserialize(d["domains"])
                d["target_roles"] = self._json_deserialize(d["target_roles"])
                d["preferred_locations"] = self._json_deserialize(d["preferred_locations"])
                d["education"] = self._json_deserialize(d["education"])
                d["projects"] = self._json_deserialize(d["projects"])
                results.append(d)
            return results
        finally:
            conn.close()

    def soft_delete_resume(self, resume_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE resumes SET deleted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), resume_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ================================================================
    # JDs
    # ================================================================

    def insert_jd(self, data: Dict) -> str:
        jd_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO jds
                   (id, user_id, url, title, company, location, salary_str,
                    salary_min, salary_max, requirements, preferred_requirements,
                    skills_required, implicit_requirements, raw_text, parsed_data,
                    source, search_keyword, platform, job_id, language,
                    industry_tag, function_tag, position_tag, auto_classified,
                    is_public, crawled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    jd_id,
                    data.get("user_id", "default"),
                    data.get("url", ""),
                    data.get("title", ""),
                    data.get("company", ""),
                    data.get("location", ""),
                    data.get("salary_str"),
                    data.get("salary_min"),
                    data.get("salary_max"),
                    self._json_serialize(data.get("requirements")),
                    self._json_serialize(data.get("preferred_requirements")),
                    self._json_serialize(data.get("skills_required", [])),
                    data.get("implicit_requirements"),
                    data.get("raw_text", ""),
                    self._json_serialize(data.get("parsed_data")),
                    data.get("source", "manual"),
                    data.get("search_keyword"),
                    data.get("platform"),
                    data.get("job_id"),
                    data.get("language", "zh"),
                    data.get("industry_tag"),
                    data.get("function_tag"),
                    data.get("position_tag"),
                    data.get("auto_classified", 1),
                    data.get("is_public", 0),
                    data.get("crawled_at", now),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return jd_id

    def get_jd(self, jd_id: str) -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM jds WHERE id = ? AND deleted_at IS NULL", (jd_id,)
            ).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            d["requirements"] = self._json_deserialize(d["requirements"])
            d["preferred_requirements"] = self._json_deserialize(d["preferred_requirements"])
            d["skills_required"] = self._json_deserialize(d["skills_required"])
            d["parsed_data"] = self._json_deserialize(d["parsed_data"])
            return d
        finally:
            conn.close()

    def list_jds(
        self,
        user_id: str = "default",
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM jds WHERE user_id = ? AND deleted_at IS NULL"
            params: list = [user_id]
            if source:
                query += " AND source = ?"
                params.append(source)
            query += " ORDER BY crawled_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["requirements"] = self._json_deserialize(d["requirements"])
                d["preferred_requirements"] = self._json_deserialize(d["preferred_requirements"])
                d["skills_required"] = self._json_deserialize(d["skills_required"])
                d["parsed_data"] = self._json_deserialize(d["parsed_data"])
                results.append(d)
            return results
        finally:
            conn.close()

    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM jds WHERE url = ? AND user_id = ? AND deleted_at IS NULL",
                (url, user_id),
            ).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            d["requirements"] = self._json_deserialize(d["requirements"])
            d["preferred_requirements"] = self._json_deserialize(d["preferred_requirements"])
            d["skills_required"] = self._json_deserialize(d["skills_required"])
            d["parsed_data"] = self._json_deserialize(d["parsed_data"])
            return d
        finally:
            conn.close()

    def search_jds(
        self,
        keyword: str,
        industry_tag: Optional[str] = None,
        function_tag: Optional[str] = None,
        position_tag: Optional[str] = None,
        user_id: str = "default",
        limit: int = 50,
    ) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = [
                "user_id = ? AND deleted_at IS NULL AND (title LIKE ? OR company LIKE ? OR raw_text LIKE ?)"
            ]
            params: list = [user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
            if industry_tag:
                conditions.append("industry_tag = ?")
                params.append(industry_tag)
            if function_tag:
                conditions.append("function_tag = ?")
                params.append(function_tag)
            if position_tag:
                conditions.append("position_tag = ?")
                params.append(position_tag)
            query = "SELECT * FROM jds WHERE " + " AND ".join(conditions)
            query += " ORDER BY crawled_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["requirements"] = self._json_deserialize(d["requirements"])
                d["preferred_requirements"] = self._json_deserialize(d["preferred_requirements"])
                d["skills_required"] = self._json_deserialize(d["skills_required"])
                d["parsed_data"] = self._json_deserialize(d["parsed_data"])
                results.append(d)
            return results
        finally:
            conn.close()

    def soft_delete_jd(self, jd_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE jds SET deleted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), jd_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ================================================================
    # Match History
    # ================================================================

    def insert_match(self, data: Dict) -> str:
        match_id = data.get("id") or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO match_history
                   (id, user_id, resume_id, jd_id, score, reasoning,
                    matched_skills, missing_skills, gaps, recommendations,
                    skill_mapping, should_apply, user_feedback, applied, applied_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    data.get("user_id", "default"),
                    data["resume_id"],
                    data["jd_id"],
                    data["score"],
                    data.get("reasoning", ""),
                    self._json_serialize(data.get("matched_skills", [])),
                    self._json_serialize(data.get("missing_skills", [])),
                    self._json_serialize(data.get("gaps", [])),
                    self._json_serialize(data.get("recommendations", [])),
                    self._json_serialize(data.get("skill_mapping", [])),
                    data.get("should_apply", 0),
                    data.get("user_feedback"),
                    data.get("applied", 0),
                    data.get("applied_at"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return match_id

    def list_matches(
        self,
        resume_id: Optional[str] = None,
        jd_id: Optional[str] = None,
        user_id: str = "default",
        limit: int = 100,
    ) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = ["user_id = ? AND deleted_at IS NULL"]
            params: list = [user_id]
            if resume_id:
                conditions.append("resume_id = ?")
                params.append(resume_id)
            if jd_id:
                conditions.append("jd_id = ?")
                params.append(jd_id)
            query = "SELECT * FROM match_history WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["matched_skills"] = self._json_deserialize(d["matched_skills"])
                d["missing_skills"] = self._json_deserialize(d["missing_skills"])
                d["gaps"] = self._json_deserialize(d["gaps"])
                d["recommendations"] = self._json_deserialize(d["recommendations"])
                d["skill_mapping"] = self._json_deserialize(d["skill_mapping"])
                results.append(d)
            return results
        finally:
            conn.close()

    # ================================================================
    # Optimizations
    # ================================================================

    def insert_optimization(self, data: Dict) -> str:
        opt_id = data.get("id") or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO optimizations
                   (id, user_id, resume_id, jd_id, chunk_id,
                    optimization_type, section, original_content,
                    suggested_content, reason, user_adopted, user_rating)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opt_id,
                    data.get("user_id", "default"),
                    data.get("resume_id"),
                    data["jd_id"],
                    data.get("chunk_id"),
                    data.get("optimization_type", "modify"),
                    data.get("section"),
                    data.get("original_content"),
                    data.get("suggested_content"),
                    data.get("reason", ""),
                    data.get("user_adopted", 0),
                    data.get("user_rating"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return opt_id

    def list_optimizations(
        self,
        jd_id: Optional[str] = None,
        user_id: str = "default",
    ) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = ["user_id = ?"]
            params: list = [user_id]
            if jd_id:
                conditions.append("jd_id = ?")
                params.append(jd_id)
            query = "SELECT * FROM optimizations WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE optimizations SET user_adopted = ? WHERE id = ?",
                (adopted, opt_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ================================================================
    # Knowledge Chunks
    # ================================================================

    def insert_chunk(self, data: Dict) -> str:
        chunk_id = data.get("id") or str(uuid.uuid4())
        emb = data.get("embedding")
        emb_dim = data.get("embedding_dim")
        if emb_dim is None and isinstance(emb, (list, tuple)):
            emb_dim = len(emb)
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO knowledge_chunks
                   (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                    keywords, embedding, embedding_dim)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    data.get("user_id", "default"),
                    data["jd_id"],
                    data["chunk_index"],
                    data["chunk_text"],
                    data.get("chunk_type", "full"),
                    self._json_serialize(data.get("keywords", [])),
                    self._embedding_to_blob(emb),
                    emb_dim,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return chunk_id

    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict]) -> List[str]:
        ids = []
        conn = self._get_conn()
        try:
            for i, chunk in enumerate(chunks):
                chunk["jd_id"] = jd_id
                chunk["chunk_index"] = i
                chunk_id = chunk.get("id") or str(uuid.uuid4())
                emb = chunk.get("embedding")
                emb_dim = chunk.get("embedding_dim")
                if emb_dim is None and isinstance(emb, (list, tuple)):
                    emb_dim = len(emb)
                conn.execute(
                    """INSERT INTO knowledge_chunks
                       (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                        keywords, embedding, embedding_dim)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id,
                        chunk.get("user_id", "default"),
                        jd_id,
                        i,
                        chunk["chunk_text"],
                        chunk.get("chunk_type", "full"),
                        self._json_serialize(chunk.get("keywords", [])),
                        self._embedding_to_blob(emb),
                        emb_dim,
                    ),
                )
                ids.append(chunk_id)
            conn.commit()
        finally:
            conn.close()
        return ids

    def get_chunks_by_jd(self, jd_id: str) -> List[Dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE jd_id = ? AND deleted_at IS NULL ORDER BY chunk_index",
                (jd_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["keywords"] = self._json_deserialize(d["keywords"])
                results.append(d)
            return results
        finally:
            conn.close()

    # ================================================================
    # Quality Checks
    # ================================================================

    def insert_quality_check(self, data: Dict) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO quality_checks
                   (check_type, target_table, target_id, score, details, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    data["check_type"],
                    data.get("target_table"),
                    data.get("target_id"),
                    data.get("score"),
                    self._json_serialize(data.get("details", {})),
                    data.get("user_id", "default"),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def list_quality_checks(
        self,
        check_type: Optional[str] = None,
        target_table: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = []
            params: list = []
            if check_type:
                conditions.append("check_type = ?")
                params.append(check_type)
            if target_table:
                conditions.append("target_table = ?")
                params.append(target_table)
            query = "SELECT * FROM quality_checks"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY checked_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["details"] = self._json_deserialize(d["details"])
                results.append(d)
            return results
        finally:
            conn.close()

    # ================================================================
    # PDF Ingestion & Vector Search
    # ================================================================

    def insert_jd_from_parsed_pdf(
        self,
        pdf_path: str,
        user_id: str = "default",
        classifier: Any = None,
    ) -> str:
        """Parse a PDF document, generate chunks with context, and persist.

        Extracts a JD from the PDF (using title/company from content or
        file metadata), inserts it into the ``jds`` table, then parses
        the document into semantic chunks enriched with context descriptions
        and stores them in ``knowledge_chunks``.

        If an ``embedding_model`` is configured in settings, an embedding
        for each chunk is also generated and stored.

        Args:
            pdf_path: Path to the PDF file.
            user_id: Owner user ID.
            classifier: Optional ``JDClassifier`` instance for auto-classifying
                         the JD. If ``None`` and ``JOB_TAXONOMY_PATH`` is
                         set, the classifier is instantiated automatically.

        Returns:
            The ``jd_id`` of the inserted JD record.
        """
        raise NotImplementedError

    def search_similar_chunks(
        self,
        query_text: str,
        top_k: int = 5,
        filter_chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """Vector-similarity search over knowledge chunks.

        Embeds ``query_text`` and finds the ``top_k`` chunks with the
        highest cosine similarity.  Each result dict contains at least:

        - ``chunk_text`` — the raw chunk content
        - ``context`` — context description (50-150 chars)
        - ``heading_path`` — list of ancestor heading texts
        - ``metadata`` — dict with source/title/version info
        - ``similarity`` — float in [0, 1] (1 = identical)

        Falls back to text-based LIKE search if no embedding service is
        configured.

        Args:
            query_text: The search query string.
            top_k: Maximum number of results.
            filter_chunk_type: If set, only return chunks of this type
                               (e.g. ``"responsibility"``).
            user_id: If set, scope results to this user.

        Returns:
            List of chunk dicts sorted by similarity descending.
        """
        raise NotImplementedError

    # ================================================================
    # Stats
    # ================================================================

    def get_stats(self) -> Dict:
        conn = self._get_conn()
        try:
            stats = {}
            for table in ["resumes", "jds", "match_history", "optimizations", "knowledge_chunks"]:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NULL")
                stats[table] = cursor.fetchone()[0]
            return stats
        finally:
            conn.close()
