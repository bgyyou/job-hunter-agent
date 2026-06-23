"""PostgreSQL + pgvector backend for JobHunterDB."""

import json
import os
import ssl
import urllib.request
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from loguru import logger

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from database.backends import BaseBackend


class PostgresBackend(BaseBackend):
    """PostgreSQL + pgvector implementation of the database backend."""

    def __init__(self, db_url: Optional[str] = None):
        if db_url is None:
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://jobhunter:jobhunter@localhost:5432/jobhunter"
            )
        self.db_url = db_url
        self._conn = None
        self._ensure_connection()
        self._init_db()

    def _ensure_connection(self):
        if self._conn is None or self._conn.closed:
            if psycopg2 is None:
                raise ImportError("psycopg2 is required for PostgreSQL backend. Install with: pip install psycopg2-binary")
            self._conn = psycopg2.connect(self.db_url)
            self._conn.set_session(autocommit=True)
            logger.info(f"PostgreSQL backend connected: {self.db_url}")

    def _close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    def _execute(self, query, params=None):
        """Execute a query with auto-reconnect on failure."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            return cursor
        except Exception:
            logger.warning("Connection lost during execute, reconnecting…")
            self._ensure_connection()
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            return cursor

    def _fetchall(self, query, params=None):
        """Execute and fetch all rows as list of dicts."""
        cursor = self._execute(query, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def _get_conn(self):
        """Get a live connection, reconnecting if necessary."""
        if self._conn is None or self._conn.closed:
            self._ensure_connection()
        return self._conn

    def _init_db(self):
        schema_path = Path(__file__).parent.parent.parent / "data" / "schema_pg.sql"
        if schema_path.exists():
            with open(schema_path, encoding="utf-8") as f:
                self._execute(f.read())
            logger.info(f"PostgreSQL schema initialized from {schema_path}")
        else:
            logger.warning(f"schema_pg.sql not found at {schema_path}, skipping PG init")

        # 编号迁移：database/migrations_pg/NNN_*.sql（PG 方言）
        # 与 SQLite 走独立目录，避免 datetime('now') 等 SQLite-only 语法污染 PG
        mig_dir = Path(__file__).parent.parent.parent / "database" / "migrations_pg"
        if mig_dir.exists():
            for mig_file in sorted(mig_dir.glob("*.sql")):
                try:
                    with open(mig_file, encoding="utf-8") as f:
                        self._execute(f.read())
                    logger.info(f"migration: applied {mig_file.name}")
                except Exception as exc:
                    logger.warning(f"migration {mig_file.name} failed: {exc}")

    def _json_serialize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _json_deserialize(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        return value  # JSONB already returns Python types from psycopg2

    def _embedding_to_pgvector(self, embedding: Optional[List[float]]) -> Optional[str]:
        """Convert Python list to pgvector vector string, e.g. '[0.1,0.2,...]'."""
        if embedding is None:
            return None
        if not isinstance(embedding, (list, str)):
            return str(embedding)
        if isinstance(embedding, str):
            return embedding  # already a pgvector string
        return "[" + ",".join(f"{v:.7f}" for v in embedding) + "]"

    def _heading_path_to_pg(self, path: Optional[list]) -> Optional[str]:
        """Convert list to PostgreSQL TEXT[] string."""
        if path is None or len(path) == 0:
            return None
        items = ",".join(f"'{str(p).replace(chr(39), chr(39)+chr(39))}'" for p in path)
        return "{" + items + "}"

    def _deserialize_list(self, row: Dict, fields: list) -> Dict:
        for field in fields:
            row[field] = self._json_deserialize(row.get(field))
        return row

    # ==================== Resumes ====================

    def insert_resume(self, data: Dict) -> str:
        resume_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        self._execute(
            """INSERT INTO resumes
               (id, user_id, name, phone, email, summary, skills,
                experience_years, domains, target_roles, preferred_locations,
                education, projects, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at""",
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
        return resume_id

    def get_resume(self, resume_id: str) -> Optional[Dict]:
        rows = self._fetchall(
            "SELECT * FROM resumes WHERE id = %s AND deleted_at IS NULL", (resume_id,)
        )
        if not rows:
            return None
        return self._deserialize_list(rows[0], ["skills", "domains", "target_roles", "preferred_locations", "education", "projects"])

    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        rows = self._fetchall(
            "SELECT * FROM resumes WHERE user_id = %s AND deleted_at IS NULL ORDER BY updated_at DESC", (user_id,)
        )
        return [self._deserialize_list(r, ["skills", "domains", "target_roles", "preferred_locations", "education", "projects"]) for r in rows]

    def soft_delete_resume(self, resume_id: str) -> None:
        self._execute(
            "UPDATE resumes SET deleted_at = %s WHERE id = %s",
            (datetime.now().isoformat(), resume_id),
        )

    # ==================== JDs ====================

    def insert_jd(self, data: Dict) -> str:
        jd_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        self._execute(
            """INSERT INTO jds
               (id, user_id, url, title, company, location, salary_str,
                salary_min, salary_max, requirements, preferred_requirements,
                skills_required, implicit_requirements, raw_text, parsed_data,
                source, search_keyword, platform, job_id, language,
                industry_tag, function_tag, position_tag, auto_classified,
                is_public, crawled_at, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (url, user_id) DO NOTHING""",
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
        return jd_id

    def get_jd(self, jd_id: str) -> Optional[Dict]:
        rows = self._fetchall("SELECT * FROM jds WHERE id = %s AND deleted_at IS NULL", (jd_id,))
        if not rows:
            return None
        return self._deserialize_list(rows[0], ["requirements", "preferred_requirements", "skills_required", "parsed_data"])

    def list_jds(self, user_id: str = "default", source: Optional[str] = None, limit: int = 100) -> List[Dict]:
        query = "SELECT * FROM jds WHERE user_id = %s AND deleted_at IS NULL"
        params = [user_id]
        if source:
            query += " AND source = %s"; params.append(source)
        query += " ORDER BY crawled_at DESC LIMIT %s"; params.append(limit)
        rows = self._fetchall(query, params)
        return [self._deserialize_list(r, ["requirements", "preferred_requirements", "skills_required", "parsed_data"]) for r in rows]

    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        rows = self._fetchall(
            "SELECT * FROM jds WHERE url = %s AND user_id = %s AND deleted_at IS NULL", (url, user_id)
        )
        if not rows:
            return None
        return self._deserialize_list(rows[0], ["requirements", "preferred_requirements", "skills_required", "parsed_data"])

    def search_jds(self, keyword: str, industry_tag: Optional[str] = None,
                   function_tag: Optional[str] = None, position_tag: Optional[str] = None,
                   user_id: str = "default", limit: int = 50) -> List[Dict]:
        conditions = ["user_id = %s AND deleted_at IS NULL AND (title LIKE %s OR company LIKE %s OR raw_text LIKE %s)"]
        params = [user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
        if industry_tag:
            conditions.append("industry_tag = %s"); params.append(industry_tag)
        if function_tag:
            conditions.append("function_tag = %s"); params.append(function_tag)
        if position_tag:
            conditions.append("position_tag = %s"); params.append(position_tag)
        query = "SELECT * FROM jds WHERE " + " AND ".join(conditions)
        query += " ORDER BY crawled_at DESC LIMIT %s"; params.append(limit)
        rows = self._fetchall(query, params)
        return [self._deserialize_list(r, ["requirements", "preferred_requirements", "skills_required", "parsed_data"]) for r in rows]

    def soft_delete_jd(self, jd_id: str) -> None:
        now = datetime.now().isoformat()
        self._execute("UPDATE jds SET deleted_at = %s WHERE id = %s", (now, jd_id))
        # v2.1 M3: 级联软删 knowledge_chunks
        self._execute(
            "UPDATE knowledge_chunks SET deleted_at = %s WHERE jd_id = %s AND deleted_at IS NULL",
            (now, jd_id),
        )

    # ==================== Match History ====================

    def insert_match(self, data: Dict) -> str:
        match_id = data.get("id") or str(uuid.uuid4())
        self._execute(
            """INSERT INTO match_history
               (id, user_id, resume_id, jd_id, score, reasoning,
                matched_skills, missing_skills, gaps, recommendations,
                skill_mapping, should_apply, user_feedback, applied, applied_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET should_apply = EXCLUDED.should_apply""",
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
        return match_id

    def list_matches(self, resume_id: Optional[str] = None, jd_id: Optional[str] = None,
                     user_id: str = "default", limit: int = 100) -> List[Dict]:
        conditions = ["user_id = %s AND deleted_at IS NULL"]
        params = [user_id]
        if resume_id:
            conditions.append("resume_id = %s"); params.append(resume_id)
        if jd_id:
            conditions.append("jd_id = %s"); params.append(jd_id)
        query = "SELECT * FROM match_history WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT %s"; params.append(limit)
        rows = self._fetchall(query, params)
        return [self._deserialize_list(r, ["matched_skills", "missing_skills", "gaps", "recommendations", "skill_mapping"]) for r in rows]

    def update_match_applied(self, match_id: str, applied: int,
                             applied_at: Optional[str] = None) -> None:
        """v2.1 M2: 投递成功后回写 applied + 时间戳。Postgres 的 applied_at 为 TIMESTAMPTZ。"""
        if applied_at is None:
            self._execute(
                "UPDATE match_history SET applied = %s, applied_at = NOW() WHERE id = %s",
                (applied, match_id),
            )
        else:
            self._execute(
                "UPDATE match_history SET applied = %s, applied_at = %s WHERE id = %s",
                (applied, applied_at, match_id),
            )

    def update_match_feedback(self, match_id: str, feedback: str) -> None:
        """v2.1 M2: 用户反馈（accepted / read / rejected / interview）。"""
        self._execute(
            "UPDATE match_history SET user_feedback = %s WHERE id = %s",
            (feedback, match_id),
        )

    # ==================== Optimizations ====================

    def insert_optimization(self, data: Dict) -> str:
        opt_id = data.get("id") or str(uuid.uuid4())
        self._execute(
            """INSERT INTO optimizations
               (id, user_id, resume_id, jd_id, chunk_id,
                optimization_type, section, original_content,
                suggested_content, reason, user_adopted, user_rating)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (opt_id, data.get("user_id", "default"), data.get("resume_id"),
             data["jd_id"], data.get("chunk_id"),
             data.get("optimization_type", "modify"), data.get("section"),
             data.get("original_content"), data.get("suggested_content"),
             data.get("reason", ""), data.get("user_adopted", 0), data.get("user_rating")),
        )
        return opt_id

    def list_optimizations(self, jd_id: Optional[str] = None, user_id: str = "default") -> List[Dict]:
        conditions = ["user_id = %s"]
        params = [user_id]
        if jd_id:
            conditions.append("jd_id = %s"); params.append(jd_id)
        query = "SELECT * FROM optimizations WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        return self._fetchall(query, params)

    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        self._execute("UPDATE optimizations SET user_adopted = %s WHERE id = %s", (adopted, opt_id))

    # ==================== Knowledge Chunks ====================

    def insert_chunk(self, data: Dict) -> str:
        chunk_id = data.get("id") or str(uuid.uuid4())
        self._execute(
            """INSERT INTO knowledge_chunks
               (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                keywords, embedding, embedding_dim, context, heading_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (chunk_id, data.get("user_id", "default"), data["jd_id"],
             data["chunk_index"], data["chunk_text"],
             data.get("chunk_type", "full"),
             self._json_serialize(data.get("keywords", [])),
             self._embedding_to_pgvector(data.get("embedding")),
             data.get("embedding_dim"),
             data.get("context", ""),
             self._heading_path_to_pg(data.get("heading_path", []))),
        )
        return chunk_id

    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict]) -> List[str]:
        ids = []
        cursor = self._conn.cursor()
        try:
            for i, chunk in enumerate(chunks):
                chunk["jd_id"] = jd_id
                chunk["chunk_index"] = i
                chunk_id = chunk.get("id") or str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO knowledge_chunks
                       (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                        keywords, embedding, embedding_dim, context, heading_path)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (chunk_id, chunk.get("user_id", "default"), jd_id, i,
                     chunk["chunk_text"], chunk.get("chunk_type", "full"),
                     self._json_serialize(chunk.get("keywords", [])),
                     self._embedding_to_pgvector(chunk.get("embedding")),
                     chunk.get("embedding_dim"),
                     chunk.get("context", ""),
                     self._heading_path_to_pg(chunk.get("heading_path", []))),
                )
                ids.append(chunk_id)
        finally:
            cursor.close()
        return ids

    def get_chunks_by_jd(self, jd_id: str) -> List[Dict]:
        rows = self._fetchall(
            "SELECT * FROM knowledge_chunks WHERE jd_id = %s AND deleted_at IS NULL ORDER BY chunk_index", (jd_id,)
        )
        results = []
        for row in rows:
            row["keywords"] = self._json_deserialize(row.get("keywords"))
            row["heading_path"] = self._json_deserialize(row.get("heading_path"))
            # Convert pgvector string back to list for consumer compatibility
            if row.get("embedding"):
                try:
                    row["embedding"] = [
                        float(x) for x in str(row["embedding"]).strip("[]").split(",")
                    ]
                except (ValueError, AttributeError):
                    pass
            results.append(row)
        return results

    # ==================== Quality Checks ====================

    def insert_quality_check(self, data: Dict) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO quality_checks
                       (check_type, target_table, target_id, score, details, user_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (data["check_type"], data.get("target_table"), data.get("target_id"),
                     data.get("score"), self._json_serialize(data.get("details", {})),
                     data.get("user_id", "default")),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else 0
        except Exception:
            conn.rollback()
            raise

    def list_quality_checks(self, check_type: Optional[str] = None,
                            target_table: Optional[str] = None, limit: int = 100) -> List[Dict]:
        conditions = []
        params = []
        if check_type:
            conditions.append("check_type = %s"); params.append(check_type)
        if target_table:
            conditions.append("target_table = %s"); params.append(target_table)
        query = "SELECT * FROM quality_checks"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY checked_at DESC LIMIT %s"; params.append(limit)
        rows = self._fetchall(query, params)
        return [self._deserialize_list(r, ["details"]) for r in rows]

    # ================================================================
    # PDF Ingestion & Vector Search
    # ================================================================

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """v2.1 M3.3: 优先用本地 Embedder（BGE-small-zh, 512 维）。

        本地不可用时再回退到 OpenAI 兼容 API。
        """
        try:
            from tools.embedder import Embedder
            return Embedder().embed(text)
        except Exception as exc:
            logger.warning(f"Local embedder unavailable, fallback to remote API: {exc}")

        base_url = os.environ.get("EMBEDDING_URL", "")
        api_key = os.environ.get("EMBEDDING_API_KEY", "")
        if not base_url or not api_key:
            base_url = os.environ.get("OPENAI_API_BASE", "")
            api_key = os.environ.get("OPENAI_API_KEY", "")
        if not base_url or not api_key:
            return None
        return self._embed_text_sync(text, base_url, api_key)

    def insert_jd_from_parsed_pdf(
        self,
        pdf_path: str,
        user_id: str = "default",
        classifier: Any = None,
    ) -> str:
        """Parse PDF → enrich chunks → insert JD + chunks_vector.

        Flow:
          1. PDFParser.parse() → semantic chunks
          2. MultimodalDescriber.describe_figures() → figure descriptions
          3. Contextualizer.generate_context() → context for every chunk
          4. Extract JD info → insert jds table
          5. Optional classifier.classify() → tags
          6. Embed each chunk → insert into chunks_vector table
        """
        # ---------- 1. Parse ----------
        try:
            from document_parser import PDFParser
            parser = PDFParser(document_title=Path(pdf_path).stem)
            chunks = parser.parse(pdf_path)
            logger.info(f"Parsed {pdf_path} → {len(chunks)} chunks")
        except Exception as exc:
            logger.error(f"PDF parse failed: {exc}")
            raise

        # ---------- 2. Describe figures ----------
        if any(c.get("type") == "figure" for c in chunks):
            try:
                from document_parser import MultimodalDescriber
                MultimodalDescriber().describe_figures(chunks)
            except Exception as exc:
                logger.warning(f"Figure description skipped: {exc}")

        # ---------- 3. Context ----------
        try:
            from document_parser import Contextualizer
            chunks = Contextualizer().generate_context(chunks)
        except Exception as exc:
            logger.warning(f"Context generation skipped: {exc}")
            for c in chunks:
                c.setdefault("context", "[context unavailable]")

        # ---------- 4. Extract JD info ----------
        meta_chunk = next((c for c in chunks if c.get("page") == 0), None)
        meta = meta_chunk.get("metadata", {}) or {} if meta_chunk else {}
        doc_title = (
            (meta.get("document_title", "") or meta_chunk.get("content", "") or Path(pdf_path).stem).strip()
            if meta_chunk
            else Path(pdf_path).stem
        )
        para_texts = [c.get("content", "") for c in chunks if c.get("type") in ("paragraph", "list")]
        raw_text = "\n".join(para_texts)[:2000]
        url = f"pdf://{Path(pdf_path).name}"

        jd_data = {
            "url": url,
            "title": doc_title,
            "company": "",
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
        }
        jd_id = self.insert_jd(jd_data)
        logger.info(f"JD inserted: {jd_id} (title='{doc_title}')")

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
                        f"Classified '{doc_title}': industry={jd_data['industry_tag']}, "
                        f"function={jd_data['function_tag']}, position={jd_data['position_tag']}"
                    )
            except Exception as exc:
                logger.warning(f"Classification failed: {exc}")

        # ---------- 6. Embed + insert chunks_vector ----------
        conn = self._get_conn()
        cursor = conn.cursor()
        batch_success = 0
        batch_skipped = 0
        seq = 0
        try:
            for chunk in chunks:
                if chunk.get("page") == 0:
                    continue  # skip meta chunk

                chunk_text = chunk.get("content", "") or ""
                chunk_context = chunk.get("context", "") or ""
                chunk_type = chunk.get("type", "paragraph")

                # Embed
                try:
                    vec = self._get_embedding(chunk_text)
                except Exception as exc:
                    logger.warning(f"Embedding failed for chunk {seq}: {exc}")
                    vec = None

                if vec is None:
                    batch_skipped += 1
                    seq += 1
                    continue

                metadata = chunk.get("metadata", {}) or {}
                # Build metadata dict: merge doc metadata + chunk info
                meta_dict = {
                    "source": metadata.get("source", Path(pdf_path).name),
                    "document_title": metadata.get("document_title", doc_title),
                    "document_version": metadata.get("document_version", ""),
                    "chunk_type": chunk_type,
                    "page": chunk.get("page", 0),
                }
                # Include figure_description if present
                fig_desc = metadata.get("figure_description", "")
                if fig_desc:
                    meta_dict["figure_description"] = fig_desc

                try:
                    cursor.execute(
                        """INSERT INTO chunks_vector
                           (id, jd_id, chunk_index, chunk_text, chunk_context,
                            embedding, metadata, heading_path)
                           VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s)""",
                        (
                            str(uuid.uuid4()),
                            jd_id,
                            seq,
                            chunk_text,
                            chunk_context,
                            self._embedding_to_pgvector(vec),
                            self._json_serialize(meta_dict),
                            self._heading_path_to_pg(chunk.get("heading_path", [])),
                        ),
                    )
                    batch_success += 1
                except Exception as exc:
                    logger.warning(f"Insert chunk {seq} failed: {exc}")

                seq += 1
            conn.commit()
        finally:
            cursor.close()

        logger.info(
            f"chunks_vector inserted: {batch_success} OK, {batch_skipped} skipped (no embedding)"
        )
        return jd_id

    # v2.1 M3.3: chunk_type 检索加权（与 SqliteBackend 一致）
    _CHUNK_TYPE_WEIGHT = {
        "responsibility": 1.2,
        "requirement": 1.3,
        "overview": 0.8,
        "nice_to_have": 0.5,
        "full": 1.0,
    }

    def search_similar_chunks(
        self,
        query_text: str,
        top_k: int = 5,
        filter_chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """v2.1 M3.3: pgvector cosine + chunk_type 加权检索 knowledge_chunks。

        - 走 M3 写入的 knowledge_chunks（不是历史 chunks_vector）
        - 取 top_k * 3 候选后用 Python 加权排序，避免 ORDER BY 表达式失效
        - 兜底文本 LIKE
        """
        try:
            vec = self._get_embedding(query_text)
        except Exception as e:
            logger.warning(f"Embedding failed: {e}, falling back to text search")
            vec = None

        if vec is None:
            return self._text_search_fallback(query_text, top_k, filter_chunk_type, user_id)

        vec_str = self._embedding_to_pgvector(vec)

        filter_parts: List[str] = ["deleted_at IS NULL", "embedding IS NOT NULL"]
        filter_vals: list = []
        if filter_chunk_type:
            filter_parts.append("chunk_type = %s")
            filter_vals.append(filter_chunk_type)
        if user_id:
            filter_parts.append("user_id = %s")
            filter_vals.append(user_id)

        where_sql = " AND ".join(filter_parts)
        candidate_k = max(top_k * 3, top_k)

        # 提升 HNSW 召回：ef_search 应 >= 实际取的候选数（candidate_k）
        # 默认 40 在 top_k=15、candidate_k=45 时会丢召回；取 max(64, candidate_k)
        try:
            self._execute(f"SET LOCAL hnsw.ef_search = {max(64, candidate_k)}")
        except Exception:
            pass  # 旧版 pgvector 没有该参数，忽略

        query = f"""
            SELECT id, jd_id, chunk_index, chunk_text, chunk_type, keywords,
                   context, heading_path,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM knowledge_chunks
            WHERE {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        search_params = [vec_str] + filter_vals + [vec_str, candidate_k]

        rows = self._fetchall(query, search_params)

        scored: List[tuple] = []
        for row in rows:
            cos = float(row.get("similarity", 0.0) or 0.0)
            ct = row.get("chunk_type", "full") or "full"
            weight = self._CHUNK_TYPE_WEIGHT.get(ct, 1.0)
            scored.append((cos * weight, cos, ct, weight, row))

        scored.sort(key=lambda t: t[0], reverse=True)
        results: List[Dict] = []
        for ranked, cos, ct, weight, row in scored[:top_k]:
            results.append({
                "chunk_text": row.get("chunk_text", ""),
                "context": row.get("context", ""),
                "heading_path": row.get("heading_path"),
                "keywords": self._json_deserialize(row.get("keywords")),
                "chunk_type": ct,
                "chunk_weight": weight,
                "similarity": round(cos, 4),
                "ranked_score": round(ranked, 4),
                "metadata": {
                    "jd_id": row.get("jd_id"),
                    "chunk_index": row.get("chunk_index"),
                },
            })
        return results

    def _embed_text_sync(self, text: str, url: str, key: str) -> list:
        """Embed text using OpenAI-compatible API (sync, no httpx dependency)."""
        import http.client
        import ssl

        parsed = url.rstrip("/")
        host = parsed.replace("https://", "").replace("http://", "").split("/")[0]
        path = parsed.replace(parsed.split("//")[0] + "//", "/")
        if not path.startswith("/"):
            path = "/v1/embeddings"

        payload = json.dumps({
            "model": "text-embedding-3-small",
            "input": text,
            "dimensions": 1536,
        })

        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, context=ctx)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())

        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]["embedding"]
        raise ValueError(f"Embedding API returned unexpected format: {data}")

    def _text_search_fallback(self, query_text: str, top_k: int,
                              filter_chunk_type: Optional[str],
                              user_id: Optional[str]) -> List[Dict]:
        """Fallback: LIKE-based text search on knowledge_chunks when embedding is unavailable."""
        conditions = ["deleted_at IS NULL"]
        params = [f"%{query_text}%"]
        if filter_chunk_type:
            conditions.append("chunk_type = %s"); params.append(filter_chunk_type)
        if user_id:
            conditions.append("user_id = %s"); params.append(user_id)
        query = "SELECT * FROM knowledge_chunks WHERE " + " AND ".join(conditions)
        query += " AND chunk_text LIKE %s ORDER BY chunk_index LIMIT %s"
        params.extend([f"%{query_text}%", top_k])
        rows = self._fetchall(query, params)
        for row in rows:
            row["keywords"] = self._json_deserialize(row.get("keywords"))
            row["heading_path"] = self._json_deserialize(row.get("heading_path"))
            row["similarity"] = 0.0
            # Ensure required keys exist
            row.setdefault("chunk_text", row.get("chunk_text", ""))
            row.setdefault("context", "")
            row.setdefault("metadata", {})
        return rows

    # ==================== Stats ====================

    def get_stats(self) -> Dict:
        stats = {}
        for table in ["resumes", "jds", "match_history", "optimizations", "knowledge_chunks"]:
            rows = self._fetchall(f"SELECT COUNT(*) as count FROM {table} WHERE deleted_at IS NULL")
            stats[table] = rows[0]["count"] if rows else 0
        return stats
