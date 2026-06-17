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

    # v2.1 M3.3: chunk_type 检索加权
    _CHUNK_TYPE_WEIGHT = {
        "responsibility": 1.2,
        "requirement": 1.3,
        "overview": 0.8,
        "nice_to_have": 0.5,
        "full": 1.0,
    }

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
        logger.info(f"SQLite backend initialized: {self.db_path}")

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
                    salary_min, salary_max, requirements, preferred_requirements,
                    skills_required, implicit_requirements, raw_text, parsed_data,
                    source, search_keyword, platform, job_id, language,
                    industry_tag, function_tag, position_tag, auto_classified,
                    is_public, crawled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (jd_id, data.get("user_id", "default"), data.get("url", ""),
                 data.get("title", ""), data.get("company", ""), data.get("location", ""),
                 data.get("salary_str"), data.get("salary_min"), data.get("salary_max"),
                 self._json_serialize(data.get("requirements")),
                 self._json_serialize(data.get("preferred_requirements")),
                 self._json_serialize(data.get("skills_required", [])),
                 data.get("implicit_requirements"), data.get("raw_text", ""),
                 self._json_serialize(data.get("parsed_data")),
                 data.get("source", "manual"), data.get("search_keyword"),
                 data.get("platform"), data.get("job_id"), data.get("language", "zh"),
                 data.get("industry_tag"), data.get("function_tag"), data.get("position_tag"),
                 data.get("auto_classified", 1), data.get("is_public", 0),
                 data.get("crawled_at", now), now, now),
            )
            conn.commit()
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
            for field in ["requirements", "preferred_requirements", "skills_required", "parsed_data"]:
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
            return self._deserialize_all(rows, ["requirements", "preferred_requirements", "skills_required", "parsed_data"])
        finally:
            conn.close()

    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM jds WHERE url = ? AND user_id = ? AND deleted_at IS NULL", (url, user_id)).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            for field in ["requirements", "preferred_requirements", "skills_required", "parsed_data"]:
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
            return self._deserialize_all(rows, ["requirements", "preferred_requirements", "skills_required", "parsed_data"])
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

    def search_similar_chunks(self, query_text: str, top_k: int = 5,
                              filter_chunk_type: Optional[str] = None,
                              user_id: Optional[str] = None) -> List[Dict]:
        """v2.1 M3.3: 本地 Embedder + numpy cosine + chunk_type 加权。

        优先走向量检索；缺包/缺向量时降级 LIKE。
        """
        try:
            import numpy as np  # noqa: F401
            from tools.embedder import Embedder
            embedder = Embedder()
            q_vec = embedder.embed(query_text)
        except Exception as exc:
            logger.warning(f"Embedder unavailable, fallback to LIKE search: {exc}")
            return self._like_search_chunks(query_text, top_k, filter_chunk_type, user_id)

        conn = self._get_conn()
        try:
            conditions = ["deleted_at IS NULL", "embedding IS NOT NULL"]
            params: list = []
            if filter_chunk_type:
                conditions.append("chunk_type = ?"); params.append(filter_chunk_type)
            if user_id:
                conditions.append("user_id = ?"); params.append(user_id)
            query = "SELECT * FROM knowledge_chunks WHERE " + " AND ".join(conditions)
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        import numpy as np
        q = np.asarray(q_vec, dtype=np.float32)
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
            ct = d.get("chunk_type", "full")
            weight = self._CHUNK_TYPE_WEIGHT.get(ct, 1.0)
            ranked = cos * weight
            scored.append((ranked, cos, ct, weight, d))

        scored.sort(key=lambda t: t[0], reverse=True)
        results: List[Dict] = []
        for ranked, cos, ct, weight, d in scored[:top_k]:
            d["keywords"] = self._json_deserialize(d.get("keywords"))
            d["heading_path"] = self._json_deserialize(d.get("heading_path", "[]"))
            d["embedding"] = None  # 不回传以避免 payload 膨胀
            d["similarity"] = round(cos, 4)
            d["chunk_type"] = ct
            d["chunk_weight"] = weight
            d["ranked_score"] = round(ranked, 4)
            d.setdefault("metadata", {})
            results.append(d)
        return results

    def _like_search_chunks(self, query_text: str, top_k: int,
                            filter_chunk_type: Optional[str],
                            user_id: Optional[str]) -> List[Dict]:
        """SQLite fallback: return nearest text chunks via LIKE."""
        conn = self._get_conn()
        try:
            conditions = ["deleted_at IS NULL AND chunk_text LIKE ?"]
            params: list = [f"%{query_text}%"]
            if filter_chunk_type:
                conditions.append("chunk_type = ?"); params.append(filter_chunk_type)
            if user_id:
                conditions.append("user_id = ?"); params.append(user_id)
            query = "SELECT * FROM knowledge_chunks WHERE " + " AND ".join(conditions)
            query += " ORDER BY chunk_index LIMIT ?"
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

    # ==================== PDF Ingestion ====================

    def insert_jd_from_parsed_pdf(
        self,
        pdf_path: str,
        user_id: str = "default",
        classifier: Any = None,
    ) -> str:
        """Parse a PDF, enrich chunks, persist JD + knowledge_chunks.

        Flow:
          1. PDFParser.parse() → semantic chunks
          2. MultimodalDescriber.describe_figures() → fill figure descriptions
          3. Contextualizer.generate_context() → fill context for every chunk
          4. Extract JD info (title/company from meta or filename) → insert jds
          5. Optional classifier.classify() → set industry/function/position tags
          6. Insert all enriched chunks into knowledge_chunks
          7. Return jd_id

        Each step logs on failure but does not abort the pipeline.
        """
        # ---------- 1. Parse PDF ----------
        try:
            from document_parser import PDFParser

            parser = PDFParser(document_title=Path(pdf_path).stem)
            chunks = parser.parse(pdf_path)
            logger.info(f"Parsed {pdf_path} → {len(chunks)} chunks")
        except Exception as exc:
            logger.error(f"PDF parse failed: {exc}")
            raise

        # ---------- 2. Describe figures ----------
        has_figures = any(c.get("type") == "figure" for c in chunks)
        if has_figures:
            try:
                from document_parser import MultimodalDescriber

                MultimodalDescriber().describe_figures(chunks)
            except Exception as exc:
                logger.warning(f"Figure description skipped: {exc}")

        # ---------- 3. Generate context ----------
        try:
            from document_parser import Contextualizer

            chunks = Contextualizer().generate_context(chunks)
        except Exception as exc:
            logger.warning(f"Context generation skipped: {exc}")
            # Ensure all chunks still have a context
            for c in chunks:
                c.setdefault("context", "[context unavailable]")

        # ---------- 4. Extract JD info & insert into jds ----------
        # Find the meta chunk (page == 0) for title / company / raw_text
        meta_chunk = next((c for c in chunks if c.get("page") == 0), None)
        meta = meta_chunk.get("metadata", {}) or {}
        doc_title = (meta.get("document_title", "") or meta_chunk.get("content", "") or Path(pdf_path).stem).strip()

        # Heuristic: extract company from content or first heading
        company = ""
        first_heading = ""
        for c in chunks:
            if c.get("type") == "heading":
                first_heading = c.get("content", "")
                break

        # Build a raw_text from all paragraph chunks (first 2000 chars)
        para_texts = [c.get("content", "") for c in chunks if c.get("type") in ("paragraph", "list")]
        raw_text = "\n".join(para_texts)[:2000]

        # Use file name as synthetic URL for dedup
        url = f"pdf://{Path(pdf_path).name}"

        jd_data = {
            "url": url,
            "title": doc_title,
            "company": company,
            "location": "",
            "salary_str": None,
            "salary_min": None,
            "salary_max": None,
            "requirements": [],
            "preferred_requirements": [],
            "skills_required": [],
            "implicit_requirements": None,
            "raw_text": raw_text,
            "parsed_data": {"pdf_path": str(pdf_path), "chunk_count": len(chunks)},
            "source": "pdf",
            "search_keyword": None,
            "platform": None,
            "job_id": None,
            "language": "zh",
            "industry_tag": None,
            "function_tag": None,
            "position_tag": None,
            "auto_classified": 0,
            "is_public": 0,
            "crawled_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        jd_id = self.insert_jd(jd_data)

        # Verify JD was actually persisted (ON CONFLICT DO NOTHING may silently skip)
        existing = self.get_jd(jd_id)
        if existing is None:
            # JD was ignored by conflict — try to find by URL
            existing = self.get_jd_by_url(url)
            if existing:
                jd_id = existing["id"]
                logger.info(f"JD already exists by URL: {jd_id}")
            else:
                # Re-insert with ON CONFLICT DO UPDATE
                self._insert_jd_upsert(jd_id, jd_data)
                logger.info(f"JD upserted: {jd_id}")

        logger.info(f"JD inserted/verified: {jd_id} (title='{doc_title}')")

        # ---------- 5. Classify ----------
        if classifier is not None:
            try:
                result = classifier.classify(doc_title, raw_text)
                if isinstance(result, dict):
                    jd_data["industry_tag"] = result.get("industry_tag")
                    jd_data["function_tag"] = result.get("function_tag")
                    jd_data["position_tag"] = result.get("position_tag")
                    jd_data["auto_classified"] = 1
                    logger.info(
                        f"Classified JD '{doc_title}': "
                        f"industry={jd_data['industry_tag']}, "
                        f"function={jd_data['function_tag']}, "
                        f"position={jd_data['position_tag']}"
                    )
            except Exception as exc:
                logger.warning(f"Classification failed: {exc}")

        # ---------- 6. Persist chunks ----------
        chunk_records = []
        # Map parser chunk types to DB schema-allowed values
        # DB accepts: overview, responsibility, requirement, nice_to_have, full
        TYPE_MAP = {
            "heading": "full",
            "paragraph": "full",
            "list": "full",
            "table": "full",
            "figure": "full",
            "footnote": "full",
        }
        for i, chunk in enumerate(chunks):
            if chunk.get("page") == 0:
                continue  # skip meta chunk
            try:
                chunk_record = {
                    "user_id": user_id,
                    "jd_id": jd_id,
                    "chunk_index": i,
                    "chunk_text": chunk.get("content", ""),
                    "chunk_type": TYPE_MAP.get(chunk.get("type", "full"), "full"),
                    "keywords": chunk.get("metadata", {}).get("keywords", []),
                    "embedding": None,  # vector search handled separately
                    "embedding_dim": None,
                    "context": chunk.get("context", ""),
                    "heading_path": chunk.get("heading_path", []),
                }
                chunk_records.append(chunk_record)
            except Exception as exc:
                logger.warning(f"Skipping chunk {i}: {exc}")

        if chunk_records:
            inserted_ids = self.insert_chunks_batch(jd_id, chunk_records)
            logger.info(f"Inserted {len(inserted_ids)} chunks for JD {jd_id}")

        return jd_id

    def _insert_jd_upsert(self, jd_id: str, data: Dict) -> None:
        """Insert or update a JD (avoids ON CONFLICT DO NOTHING silent skip)."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO jds
                   (id, user_id, url, title, company, location, salary_str,
                    salary_min, salary_max, requirements, preferred_requirements,
                    skills_required, implicit_requirements, raw_text, parsed_data,
                    source, search_keyword, platform, job_id, language,
                    industry_tag, function_tag, position_tag, auto_classified,
                    is_public, crawled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET
                     title=EXCLUDED.title, company=EXCLUDED.company,
                     raw_text=EXCLUDED.raw_text, parsed_data=EXCLUDED.parsed_data,
                     updated_at=EXCLUDED.updated_at""",
                (
                    jd_id, data.get("user_id", "default"), data.get("url", ""),
                    data.get("title", ""), data.get("company", ""), data.get("location", ""),
                    data.get("salary_str"), data.get("salary_min"), data.get("salary_max"),
                    self._json_serialize(data.get("requirements")),
                    self._json_serialize(data.get("preferred_requirements")),
                    self._json_serialize(data.get("skills_required", [])),
                    data.get("implicit_requirements"), data.get("raw_text", ""),
                    self._json_serialize(data.get("parsed_data")),
                    data.get("source", "manual"), data.get("search_keyword"),
                    data.get("platform"), data.get("job_id"), data.get("language", "zh"),
                    data.get("industry_tag"), data.get("function_tag"), data.get("position_tag"),
                    data.get("auto_classified", 1), data.get("is_public", 0),
                    data.get("crawled_at", now), now, now,
                ),
            )
            conn.commit()
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

    # ==================== Helpers ====================

    def _deserialize_all(self, rows, json_fields: list) -> List[Dict]:
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            for field in json_fields:
                d[field] = self._json_deserialize(d[field])
            results.append(d)
        return results
