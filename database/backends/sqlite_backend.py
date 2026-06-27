"""SQLite backend for JobHunterDB."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

from database.backends import BaseBackend


class SqliteBackend(BaseBackend):
    """SQLite implementation of the database backend."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "data" / "jobhunter_v2.db")
        self.db_path = db_path
        self._init_db()

    # v2.1 M3.3: 嵌入向量 ↔ BLOB 互转
    @staticmethod
    def _embedding_to_blob(embedding) -> Optional[bytes]:
        if embedding is None:
            return None
        if isinstance(embedding, (bytes, bytearray)):
            return bytes(embedding)
        try:
            return json.dumps(list(embedding)).encode("utf-8")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _blob_to_embedding(blob) -> Optional[List[float]]:
        if blob is None:
            return None
        if isinstance(blob, (bytes, bytearray)):
            try:
                return json.loads(bytes(blob).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
        if isinstance(blob, str):
            try:
                return json.loads(blob)
            except json.JSONDecodeError:
                return None
        if isinstance(blob, list):
            return blob
        return None

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        schema_path = Path(__file__).parent.parent.parent / "data" / "schema.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._apply_idempotent_migrations(conn)
        logger.info(f"SQLite backend initialized: {self.db_path}")

    def _apply_idempotent_migrations(self, conn: sqlite3.Connection) -> None:
        """Bring older DBs up to current schema (idempotent — safe to run every startup)."""
        # v2.1 M3: knowledge_chunks.legacy column
        cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_chunks)").fetchall()}
        if "legacy" not in cols:
            conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN legacy INTEGER NOT NULL DEFAULT 0")
            logger.info("migration: added knowledge_chunks.legacy column")

        # 编号迁移文件：database/migrations/NNN_description.sql
        mig_dir = Path(__file__).parent.parent.parent / "database" / "migrations"
        if not mig_dir.exists():
            return

        # 004 迁移前检查：jds 表是否还有旧字段
        jds_cols = {r[1] for r in conn.execute("PRAGMA table_info(jds)").fetchall()}
        has_legacy_jd_fields = "requirements" in jds_cols

        for mig_file in sorted(mig_dir.glob("*.sql")):
            # 004 幂等防护：jds 已迁移过就直接跳过
            if not has_legacy_jd_fields and "004_" in mig_file.name:
                logger.info(f"migration: skip {mig_file.name} (jds already on v3 schema)")
                continue
            logger.info(f"migration: applying {mig_file.name}")
            # 注：executescript 会先 COMMIT 当前事务，外层 BEGIN 无效。如果中途崩，
            # 半成品落地；幂等防御只能写在每个 .sql 内部（如 004 顶部的
            # DROP TABLE IF EXISTS jds_v3）。
            conn.executescript(mig_file.read_text(encoding="utf-8"))

    def _row_to_dict(self, row: sqlite3.Row) -> Optional[Dict]:
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

    # ==================== Resumes ====================

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
                (resume_id, data.get("user_id", "default"), data.get("name", ""),
                 data.get("phone"), data.get("email"), data.get("summary"),
                 self._json_serialize(data.get("skills", [])),
                 data.get("experience_years", 0),
                 self._json_serialize(data.get("domains", [])),
                 self._json_serialize(data.get("target_roles", [])),
                 self._json_serialize(data.get("preferred_locations", [])),
                 self._json_serialize(data.get("education", [])),
                 self._json_serialize(data.get("projects", [])), now),
            )
            conn.commit()
        finally:
            conn.close()
        return resume_id

    def get_resume(self, resume_id: str) -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM resumes WHERE id = ? AND deleted_at IS NULL", (resume_id,)).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            for field in ["skills", "domains", "target_roles", "preferred_locations", "education", "projects"]:
                d[field] = self._json_deserialize(d[field])
            return d
        finally:
            conn.close()

    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM resumes WHERE user_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC", (user_id,)).fetchall()
            return self._deserialize_all(rows, ["skills", "domains", "target_roles", "preferred_locations", "education", "projects"])
        finally:
            conn.close()

    def soft_delete_resume(self, resume_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute("UPDATE resumes SET deleted_at = ? WHERE id = ?", (datetime.now().isoformat(), resume_id))
            conn.commit()
        finally:
            conn.close()

    # ==================== JDs ====================

    def insert_jd(self, data: Dict) -> str:
        jd_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO jds
                   (id, user_id, url, title, company, location, salary_str,
                    salary_min, salary_max, parsed_sections, tags, raw_text,
                    source, search_keyword, platform, job_id, language,
                    industry_tag, function_tag, position_tag, auto_classified,
                    is_public, crawled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (jd_id, data.get("user_id", "default"), data.get("url", ""),
                 data.get("title", ""), data.get("company", ""), data.get("location", ""),
                 data.get("salary_str"), data.get("salary_min"), data.get("salary_max"),
                 self._json_serialize(data.get("parsed_sections", {})),
                 self._json_serialize(data.get("tags", [])),
                 data.get("raw_text", ""),
                 data.get("source", "manual"), data.get("search_keyword"),
                 data.get("platform"), data.get("job_id"), data.get("language", "zh"),
                 data.get("industry_tag"), data.get("function_tag"), data.get("position_tag"),
                 data.get("auto_classified", 1), data.get("is_public", 0),
                 data.get("crawled_at", now), now, now),
            )
            conn.commit()
            # INSERT OR IGNORE 在 UNIQUE(url, user_id) 冲突时静默跳过，
            # 此处查出真实 id 返回，而非本地伪造的新 UUID
            url = data.get("url", "")
            user_id = data.get("user_id", "default")
            if url:
                row = conn.execute(
                    "SELECT id FROM jds WHERE url = ? AND user_id = ? AND deleted_at IS NULL",
                    (url, user_id),
                ).fetchone()
                if row:
                    return row[0]
        finally:
            conn.close()
        return jd_id

    def get_jd(self, jd_id: str) -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM jds WHERE id = ? AND deleted_at IS NULL", (jd_id,)).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            for field in ["parsed_sections", "tags"]:
                d[field] = self._json_deserialize(d[field])
            return d
        finally:
            conn.close()

    def list_jds(self, user_id: str = "default", source: Optional[str] = None, limit: int = 100) -> List[Dict]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM jds WHERE user_id = ? AND deleted_at IS NULL"
            params = [user_id]
            if source:
                query += " AND source = ?"; params.append(source)
            query += " ORDER BY crawled_at DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return self._deserialize_all(rows, ["parsed_sections", "tags"])
        finally:
            conn.close()

    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM jds WHERE url = ? AND user_id = ? AND deleted_at IS NULL", (url, user_id)).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            for field in ["parsed_sections", "tags"]:
                d[field] = self._json_deserialize(d[field])
            return d
        finally:
            conn.close()

    def search_jds(self, keyword: str, industry_tag: Optional[str] = None,
                   function_tag: Optional[str] = None, position_tag: Optional[str] = None,
                   user_id: str = "default", limit: int = 50) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = ["user_id = ? AND deleted_at IS NULL AND (title LIKE ? OR company LIKE ? OR raw_text LIKE ?)"]
            params = [user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
            if industry_tag:
                conditions.append("industry_tag = ?"); params.append(industry_tag)
            if function_tag:
                conditions.append("function_tag = ?"); params.append(function_tag)
            if position_tag:
                conditions.append("position_tag = ?"); params.append(position_tag)
            query = "SELECT * FROM jds WHERE " + " AND ".join(conditions)
            query += " ORDER BY crawled_at DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return self._deserialize_all(rows, ["parsed_sections", "tags"])
        finally:
            conn.close()

    def soft_delete_jd(self, jd_id: str) -> None:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("UPDATE jds SET deleted_at = ? WHERE id = ?", (now, jd_id))
            # v2.1 M3: 级联软删 knowledge_chunks，避免向量检索命中已删 JD 的残骸
            conn.execute(
                "UPDATE knowledge_chunks SET deleted_at = ? WHERE jd_id = ? AND deleted_at IS NULL",
                (now, jd_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ==================== Match History ====================

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
                (match_id, data.get("user_id", "default"), data["resume_id"], data["jd_id"],
                 data["score"], data.get("reasoning", ""),
                 self._json_serialize(data.get("matched_skills", [])),
                 self._json_serialize(data.get("missing_skills", [])),
                 self._json_serialize(data.get("gaps", [])),
                 self._json_serialize(data.get("recommendations", [])),
                 self._json_serialize(data.get("skill_mapping", [])),
                 data.get("should_apply", 0), data.get("user_feedback"),
                 data.get("applied", 0), data.get("applied_at")),
            )
            conn.commit()
        finally:
            conn.close()
        return match_id

    def list_matches(self, resume_id: Optional[str] = None, jd_id: Optional[str] = None,
                     user_id: str = "default", limit: int = 100) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = ["user_id = ? AND deleted_at IS NULL"]
            params = [user_id]
            if resume_id:
                conditions.append("resume_id = ?"); params.append(resume_id)
            if jd_id:
                conditions.append("jd_id = ?"); params.append(jd_id)
            query = "SELECT * FROM match_history WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return self._deserialize_all(rows, ["matched_skills", "missing_skills", "gaps", "recommendations", "skill_mapping"])
        finally:
            conn.close()

    def update_match_applied(self, match_id: str, applied: int,
                             applied_at: Optional[str] = None) -> None:
        """v2.1 M2: 投递成功后回写 applied=1 + 时间戳。"""
        if applied_at is None:
            applied_at = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE match_history SET applied = ?, applied_at = ? WHERE id = ?",
                (applied, applied_at, match_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_match_feedback(self, match_id: str, feedback: str) -> None:
        """v2.1 M2: 用户反馈（accepted / read / rejected / interview）。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE match_history SET user_feedback = ? WHERE id = ?",
                (feedback, match_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ==================== Optimizations ====================

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
                (opt_id, data.get("user_id", "default"), data.get("resume_id"),
                 data["jd_id"], data.get("chunk_id"),
                 data.get("optimization_type", "modify"), data.get("section"),
                 data.get("original_content"), data.get("suggested_content"),
                 data.get("reason", ""), data.get("user_adopted", 0), data.get("user_rating")),
            )
            conn.commit()
        finally:
            conn.close()
        return opt_id

    def list_optimizations(self, jd_id: Optional[str] = None, user_id: str = "default") -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = ["user_id = ?"]
            params = [user_id]
            if jd_id:
                conditions.append("jd_id = ?"); params.append(jd_id)
            query = "SELECT * FROM optimizations WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC"
            return [self._row_to_dict(r) for r in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        conn = self._get_conn()
        try:
            conn.execute("UPDATE optimizations SET user_adopted = ? WHERE id = ?", (adopted, opt_id))
            conn.commit()
        finally:
            conn.close()

    # ==================== Knowledge Chunks ====================

    def insert_chunk(self, data: Dict) -> str:
        chunk_id = data.get("id") or str(uuid.uuid4())
        emb_blob = self._embedding_to_blob(data.get("embedding"))
        emb_dim = data.get("embedding_dim")
        if emb_dim is None and isinstance(data.get("embedding"), (list, tuple)):
            emb_dim = len(data["embedding"])
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO knowledge_chunks
                   (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                    keywords, embedding, embedding_dim, context, heading_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk_id, data.get("user_id", "default"), data["jd_id"],
                 data["chunk_index"], data["chunk_text"],
                 data.get("chunk_type", "full"),
                 self._json_serialize(data.get("keywords", [])),
                 emb_blob, emb_dim,
                 data.get("context", ""), self._json_serialize(data.get("heading_path", []))),
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
                emb_blob = self._embedding_to_blob(chunk.get("embedding"))
                emb_dim = chunk.get("embedding_dim")
                if emb_dim is None and isinstance(chunk.get("embedding"), (list, tuple)):
                    emb_dim = len(chunk["embedding"])
                conn.execute(
                    """INSERT INTO knowledge_chunks
                       (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                        keywords, embedding, embedding_dim, context, heading_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chunk_id, chunk.get("user_id", "default"), jd_id, i,
                     chunk["chunk_text"], chunk.get("chunk_type", "full"),
                     self._json_serialize(chunk.get("keywords", [])),
                     emb_blob, emb_dim,
                     chunk.get("context", ""), self._json_serialize(chunk.get("heading_path", []))),
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
                "SELECT * FROM knowledge_chunks WHERE jd_id = ? AND deleted_at IS NULL ORDER BY chunk_index", (jd_id,)).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["keywords"] = self._json_deserialize(d["keywords"])
                d["heading_path"] = self._json_deserialize(d.get("heading_path", "[]"))
                d["embedding"] = self._blob_to_embedding(d.get("embedding"))
                results.append(d)
            return results
        finally:
            conn.close()

    # ==================== Quality Checks ====================

    def insert_quality_check(self, data: Dict) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO quality_checks
                   (check_type, target_table, target_id, score, details, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (data["check_type"], data.get("target_table"), data.get("target_id"),
                 data.get("score"), self._json_serialize(data.get("details", {})),
                 data.get("user_id", "default")),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def list_quality_checks(self, check_type: Optional[str] = None,
                            target_table: Optional[str] = None, limit: int = 100) -> List[Dict]:
        conn = self._get_conn()
        try:
            conditions = []
            params = []
            if check_type:
                conditions.append("check_type = ?"); params.append(check_type)
            if target_table:
                conditions.append("target_table = ?"); params.append(target_table)
            query = "SELECT * FROM quality_checks"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY checked_at DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["details"] = self._json_deserialize(d["details"])
                results.append(d)
            return results
        finally:
            conn.close()

    # ==================== Vector Search ====================

    def vector_search(self, query_embedding: List[float], top_k: int = 5,
                      filter_chunk_type: Optional[str] = None,
                      user_id: Optional[str] = None,
                      filter_position: Optional[str] = None) -> List[Dict]:
        """Pure numpy cosine over knowledge_chunks. No re-weighting / filtering.

        Chunk_type weighting + min_similarity cutoff live in
        ``services.retrieval_service.RetrievalService``. ``filter_position`` is a
        hard JOIN on ``jds.position_tag`` so cross-industry chunks for the same
        position (e.g. "产品经理" in both 互联网 and 快消) are co-retrieved.
        """
        import numpy as np

        conn = self._get_conn()
        try:
            conditions = ["kc.deleted_at IS NULL", "kc.embedding IS NOT NULL", "kc.legacy = 0"]
            params: list = []
            if filter_chunk_type:
                conditions.append("kc.chunk_type = ?"); params.append(filter_chunk_type)
            if user_id:
                conditions.append("kc.user_id = ?"); params.append(user_id)
            if filter_position:
                conditions.append("j.position_tag = ?"); params.append(filter_position)
            query = (
                "SELECT kc.*, j.industry_tag AS jd_industry_tag, "
                "j.function_tag AS jd_function_tag, j.position_tag AS jd_position_tag "
                "FROM knowledge_chunks kc "
                "LEFT JOIN jds j ON j.id = kc.jd_id "
                "WHERE " + " AND ".join(conditions)
            )
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q)) or 1.0

        scored: List[tuple] = []
        for row in rows:
            d = self._row_to_dict(row)
            vec = self._blob_to_embedding(d.get("embedding"))
            if not vec:
                continue
            v = np.asarray(vec, dtype=np.float32)
            if v.shape != q.shape:
                continue
            v_norm = float(np.linalg.norm(v)) or 1.0
            cos = float(np.dot(q, v) / (q_norm * v_norm))
            scored.append((cos, d))

        scored.sort(key=lambda t: t[0], reverse=True)
        results: List[Dict] = []
        for cos, d in scored[:top_k]:
            d["keywords"] = self._json_deserialize(d.get("keywords"))
            d["heading_path"] = self._json_deserialize(d.get("heading_path", "[]"))
            d["embedding"] = None
            d["similarity"] = round(cos, 4)
            d.setdefault("metadata", {})
            results.append(d)
        return results

    def like_search_chunks(self, query_text: str, top_k: int = 5,
                           filter_chunk_type: Optional[str] = None,
                           user_id: Optional[str] = None,
                           filter_position: Optional[str] = None) -> List[Dict]:
        """LIKE fallback. Same output shape as ``vector_search`` (similarity=0.0)."""
        conn = self._get_conn()
        try:
            conditions = ["kc.deleted_at IS NULL AND kc.chunk_text LIKE ?", "kc.legacy = 0"]
            params: list = [f"%{query_text}%"]
            if filter_chunk_type:
                conditions.append("kc.chunk_type = ?"); params.append(filter_chunk_type)
            if user_id:
                conditions.append("kc.user_id = ?"); params.append(user_id)
            if filter_position:
                conditions.append("j.position_tag = ?"); params.append(filter_position)
            query = (
                "SELECT kc.*, j.industry_tag AS jd_industry_tag, "
                "j.function_tag AS jd_function_tag, j.position_tag AS jd_position_tag "
                "FROM knowledge_chunks kc "
                "LEFT JOIN jds j ON j.id = kc.jd_id "
                "WHERE " + " AND ".join(conditions)
            )
            query += " ORDER BY kc.chunk_index LIMIT ?"
            params.append(top_k)
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(row)
                d["keywords"] = self._json_deserialize(d["keywords"])
                d["heading_path"] = self._json_deserialize(d.get("heading_path", "[]"))
                d["embedding"] = None
                d["similarity"] = 0.0
                d.setdefault("metadata", {})
                results.append(d)
            return results
        finally:
            conn.close()

    # ==================== Stats ====================

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

    # ==================== Skeleton Cache ====================

    def get_skeleton_cache(self, position: str, industry: str,
                           function: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT skeleton_text, n_chunks, source, industries_covered
                FROM skeleton_cache
                WHERE position = ? AND industry = ?
                  AND (function IS NULL OR function = ?)
                  AND expires_at > datetime('now')
                ORDER BY function IS NOT NULL DESC, updated_at DESC
                LIMIT 1
                """,
                (position, industry, function),
            ).fetchone()
            if not row:
                return None
            result = self._row_to_dict(row)
            result["industries_covered"] = self._json_deserialize(result.get("industries_covered")) or []
            return result
        finally:
            conn.close()

    def set_skeleton_cache(self, position: str, industry: str,
                           skeleton: Dict[str, Any],
                           function: Optional[str] = None,
                           ttl_hours: int = 24) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO skeleton_cache
                    (position, industry, function, skeleton_text, n_chunks,
                     source, industries_covered, expires_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, datetime('now', ?), datetime('now'))
                ON CONFLICT(position, industry, function) DO UPDATE SET
                    skeleton_text = excluded.skeleton_text,
                    n_chunks = excluded.n_chunks,
                    source = excluded.source,
                    industries_covered = excluded.industries_covered,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    position,
                    industry,
                    function,
                    skeleton.get("text", ""),
                    skeleton.get("n_chunks", 0),
                    skeleton.get("source", "rag"),
                    self._json_serialize(skeleton.get("industries_covered", [])),
                    f"+{ttl_hours} hours",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ==================== LLM Observability ====================

    def insert_llm_call(self, data: Dict[str, Any]) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO llm_calls
                    (request_id, model, endpoint, operation, prompt_tokens,
                     completion_tokens, total_tokens, latency_ms, status,
                     error_type, error_message, metadata, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    data.get("request_id"),
                    data.get("model", ""),
                    data.get("endpoint"),
                    data.get("operation", "analyze"),
                    data.get("prompt_tokens", 0),
                    data.get("completion_tokens", 0),
                    data.get("total_tokens", 0),
                    data.get("latency_ms", 0),
                    data.get("status", "success"),
                    data.get("error_type"),
                    data.get("error_message"),
                    self._json_serialize(data.get("metadata")),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def list_llm_calls(self, model: Optional[str] = None,
                       operation: Optional[str] = None,
                       status: Optional[str] = None,
                       limit: int = 100) -> List[Dict]:
        conn = self._get_conn()
        try:
            where = ["1=1"]
            params: List[Any] = []
            if model:
                where.append("model = ?")
                params.append(model)
            if operation:
                where.append("operation = ?")
                params.append(operation)
            if status:
                where.append("status = ?")
                params.append(status)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT * FROM llm_calls
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return self._deserialize_all(rows, json_fields=["metadata"])
        finally:
            conn.close()

    # ==================== Helpers ====================

    def _deserialize_all(self, rows, json_fields: list) -> List[Dict]:
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            for field in json_fields:
                d[field] = self._json_deserialize(d[field])
            results.append(d)
        return results
