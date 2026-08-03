"""SQLite backend for JobHunterDB."""

import json
import sqlite3
import struct
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from loguru import logger

from database.backends import BaseBackend


# v4 P0-模块 3: BGE-small-zh-v1.5 固定 512 维，vec0 虚拟表 schema 对齐这个常量
_BGE_DIM = 512

# v4 P0-模块 3: vec0 虚拟表名；knowledge_chunks_vec 的 rowid == knowledge_chunks.rowid
_VEC0_TABLE = "knowledge_chunks_vec"


class SqliteBackend(BaseBackend):
    """SQLite implementation of the database database (sqlite-vec enhanced)."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "data" / "jobhunter_v2.db")
        self.db_path = db_path
        # v4 P0-模块 3: 标记 sqlite-vec 是否可用；vector_search 据此选择 vec0 路径或 numpy fallback
        self._sqlite_vec_available: bool = False
        self._init_db()

    # ------------------------------------------------------------------
    # v4 P0-模块 3: 嵌入向量 ↔ float32 binary BLOB 互转（替代旧 json 格式）
    # ------------------------------------------------------------------
    #
    # 旧格式 (v2.1 M3.3)：json.dumps(list(embedding)) → 11KB/条
    # 新格式 (v4 P0-模块 3)：numpy.float32() → 2KB/条（5x 压缩）
    #
    # _blob_to_embedding 同时支持两种格式以保证向后读取旧数据；
    # 但 _embedding_to_blob 只写新格式（CLAUDE.md "不做向后兼容 hack"）。
    @staticmethod
    def _embedding_to_blob(embedding) -> Optional[bytes]:
        """list[float] / numpy.ndarray → float32 LE bytes (2KB @ 512-dim)."""
        if embedding is None:
            return None
        if isinstance(embedding, (bytes, bytearray)):
            # 已序列化的 BLOB：按 float32 binary 解析（vec0 写入路径会用 numpy 数组，
            # 此分支主要服务 numpy → .tobytes() 的等价路径）
            return bytes(embedding)
        try:
            import numpy as np
            arr = np.asarray(embedding, dtype=np.float32)
            return arr.tobytes()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _blob_to_embedding(blob) -> Optional[List[float]]:
        """bytes → list[float]；兼容旧 json.dumps 格式（仅读取期）。"""
        if blob is None:
            return None
        if isinstance(blob, list):
            return blob
        raw = bytes(blob) if isinstance(blob, (bytes, bytearray)) else (
            blob.encode("utf-8") if isinstance(blob, str) else None
        )
        if raw is None:
            return None
        # 新格式：长度是 4 的倍数（即 float32 binary，对齐 512-dim → 2048 bytes）
        n = len(raw)
        if n > 0 and n % 4 == 0:
            try:
                import numpy as np
                arr = np.frombuffer(raw, dtype=np.float32)
                # 合理性检查：所有元素都是有限数（NaN / inf 不是合法 BGE 输出）
                if arr.size > 0 and np.all(np.isfinite(arr)):
                    return arr.tolist()
            except (ValueError, TypeError):
                pass
        # 旧格式：json.dumps（首字节是 '{'、'['、'-' 或数字），失败则 None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------
    # v4 P0-模块 3: vec0 探测与 schema_version 帮助方法
    # ------------------------------------------------------------------
    def _vec0_available(self, conn: sqlite3.Connection) -> bool:
        """vec0 虚拟表存在 + sqlite-vec 扩展已加载 → 走 vec0 路径。"""
        if not self._sqlite_vec_available:
            return False
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_VEC0_TABLE,),
        ).fetchone()
        return row is not None

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        # v4 P0-模块 3: 加载 sqlite-vec 扩展。**每个 conn 都必须 load**（sqlite-vec
        # load 是 per-connection state，不是进程全局），self._sqlite_vec_available
        # 仅作"环境能力探测"标志，不作"已 load"标志。
        try:
            conn.enable_load_extension(True)
            import sqlite_vec  # local import 避免 CI minimal-deps 缺包时崩
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._sqlite_vec_available = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"sqlite-vec not loaded, vector_search will use numpy fallback: {exc}")
            try:
                conn.enable_load_extension(False)
            except Exception:
                pass
            self._sqlite_vec_available = False
        return conn

    def _init_db(self):
        schema_path = Path(__file__).parent.parent.parent / "data" / "schema.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return
        # v4 P0-模块 3: 用 _get_conn 让 sqlite-vec 扩展先加载，保证 migration 014
        # 的 CREATE VIRTUAL TABLE USING vec0 能成功
        with self._get_conn() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._apply_idempotent_migrations(conn)
        logger.info(f"SQLite backend initialized: {self.db_path}")

    def _apply_idempotent_migrations(self, conn: sqlite3.Connection) -> None:
        """Bring older DBs up to current schema (idempotent — safe to run every startup)."""
        # v4 M-v4-2: knowledge_chunks.legacy 列兜底（M-v4-2 完成后会被 018 DROP）
        # schema.sql 已不再带 legacy 列；老 DB 启动时若缺此列则现场补回，018 再统一 DROP。
        # 新 DB 启动序列：schema.sql 建表无 legacy → 此处补回 → 018 DROP，最终一致。
        cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_chunks)").fetchall()}
        if "legacy" not in cols:
            conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN legacy INTEGER NOT NULL DEFAULT 0")
            logger.info("migration: added knowledge_chunks.legacy column (scaffolding for 018 DROP)")

        # v2.1 N10: resumes 版本树 + 主简历字段
        resume_cols = {r[1] for r in conn.execute("PRAGMA table_info(resumes)").fetchall()}
        if "parent_resume_id" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN parent_resume_id TEXT")
            logger.info("migration: added resumes.parent_resume_id column")
        if "version" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            logger.info("migration: added resumes.version column")
        if "version_label" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN version_label TEXT")
            logger.info("migration: added resumes.version_label column")
        if "is_primary" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
            logger.info("migration: added resumes.is_primary column")
        if "experience" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN experience TEXT DEFAULT '[]'")
            logger.info("migration: added resumes.experience column")
        # v3 M-rebuild-1: resumes.achievements 顶层字段（与 experience 嵌套的 achievements 并存）
        if "achievements" not in resume_cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN achievements TEXT NOT NULL DEFAULT '[]'")
            logger.info("migration: added resumes.achievements column")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resumes_parent ON resumes(parent_resume_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resumes_primary ON resumes(user_id, is_primary)"
        )

        # v2.1 M11: jds 质量分缓存列（quality_score / quality_checked_at）
        jds_cols_v11 = {r[1] for r in conn.execute("PRAGMA table_info(jds)").fetchall()}
        if "quality_score" not in jds_cols_v11:
            conn.execute("ALTER TABLE jds ADD COLUMN quality_score REAL")
            logger.info("migration: added jds.quality_score column")
        if "quality_checked_at" not in jds_cols_v11:
            conn.execute("ALTER TABLE jds ADD COLUMN quality_checked_at TEXT")
            logger.info("migration: added jds.quality_checked_at column")
        # quality_score 上的索引（不能放在 schema.sql 否则旧 DB 启动先报"无此列"）
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jds_quality_score ON jds(quality_score)"
        )

        # v4 T1.4: llm_calls.user_id 配额统计维度 + (user_id, created_at) 复合索引
        # （013 迁移的 SQLite 实际落地处；schema.sql 里 llm_calls 无此列，
        #  PRAGMA 检查保证幂等，编号迁移文件仅作 schema_version 标记）
        llm_calls_cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)").fetchall()}
        if "user_id" not in llm_calls_cols:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
            logger.info("migration: added llm_calls.user_id column")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_user_created_at "
            "ON llm_calls(user_id, created_at)"
        )

        # 编号迁移文件：database/migrations/NNN_description.sql
        mig_dir = Path(__file__).parent.parent.parent / "database" / "migrations"
        if not mig_dir.exists():
            return

        # 004 迁移前检查：jds 表是否还有旧字段
        jds_cols = {r[1] for r in conn.execute("PRAGMA table_info(jds)").fetchall()}
        has_legacy_jd_fields = "requirements" in jds_cols

        current_version = conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()[0]
        for mig_file in sorted(mig_dir.glob("*.sql")):
            migration_version = int(mig_file.name.split("_", 1)[0])
            if migration_version <= current_version:
                continue
            # 004 幂等防护：jds 已迁移过就直接标记完成
            if not has_legacy_jd_fields and migration_version == 4:
                conn.execute(
                    "UPDATE schema_version SET version = 4, "
                    "description = 'JD schema already converged', "
                    "applied_at = datetime('now') WHERE id = 1"
                )
                current_version = 4
                logger.info(f"migration: skip {mig_file.name} (jds already on v3 schema)")
                continue
            logger.info(f"migration: applying {mig_file.name}")
            # 注：executescript 会先 COMMIT 当前事务，外层 BEGIN 无效。如果中途崩，
            # 半成品落地；幂等防御只能写在每个 .sql 内部（如 004 顶部的
            # DROP TABLE IF EXISTS jds_v3）。
            conn.executescript(mig_file.read_text(encoding="utf-8"))
            current_version = conn.execute(
                "SELECT version FROM schema_version WHERE id = 1"
            ).fetchone()[0]

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
                    experience_years, experience, domains, target_roles, preferred_locations,
                    education, projects, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (resume_id, data.get("user_id", "default"), data.get("name", ""),
                 data.get("phone"), data.get("email"), data.get("summary"),
                 self._json_serialize(data.get("skills", [])),
                 data.get("experience_years", 0),
                 self._json_serialize(data.get("experience", [])),
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
            for field in ["skills", "experience", "domains", "target_roles", "preferred_locations", "education", "projects", "achievements"]:
                d[field] = self._json_deserialize(d[field])
            return d
        finally:
            conn.close()

    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM resumes WHERE user_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC", (user_id,)).fetchall()
            return self._deserialize_all(rows, ["skills", "experience", "domains", "target_roles", "preferred_locations", "education", "projects"])
        finally:
            conn.close()

    def soft_delete_resume(self, resume_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute("UPDATE resumes SET deleted_at = ? WHERE id = ?", (datetime.now().isoformat(), resume_id))
            conn.commit()
        finally:
            conn.close()

    def set_primary_resume(self, user_id: str, resume_id: str) -> None:
        """把 resume_id 设为该 user 的主简历（同时取消其他主简历）。"""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE resumes SET is_primary = 0, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            conn.execute(
                "UPDATE resumes SET is_primary = 1, updated_at = ? WHERE id = ? AND user_id = ?",
                (now, resume_id, user_id),
            )
            conn.commit()
        finally:
            conn.close()

    def clone_resume_as_version(
        self,
        source_resume_id: str,
        new_data: Optional[Dict] = None,
    ) -> str:
        """基于 source_resume_id 复制一份新简历，version = 父版本 + 1, parent_resume_id 指向父。"""
        conn = self._get_conn()
        try:
            src = conn.execute(
                "SELECT * FROM resumes WHERE id = ? AND deleted_at IS NULL",
                (source_resume_id,),
            ).fetchone()
            if not src:
                raise ValueError(f"source resume not found: {source_resume_id}")
            src_d = dict(src)
            new_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            merge = new_data or {}
            conn.execute(
                """INSERT INTO resumes
                   (id, user_id, name, phone, email, summary, skills,
                    experience_years, domains, target_roles, preferred_locations,
                    education, projects, parent_resume_id, version,
                    version_label, is_primary, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    new_id,
                    src_d["user_id"],
                    merge.get("name", src_d["name"]),
                    merge.get("phone", src_d["phone"]),
                    merge.get("email", src_d["email"]),
                    merge.get("summary", src_d["summary"]),
                    self._json_serialize(merge.get("skills", self._json_deserialize(src_d["skills"]))),
                    merge.get("experience_years", src_d["experience_years"]),
                    self._json_serialize(merge.get("domains", self._json_deserialize(src_d["domains"]))),
                    self._json_serialize(merge.get("target_roles", self._json_deserialize(src_d["target_roles"]))),
                    self._json_serialize(merge.get("preferred_locations", self._json_deserialize(src_d["preferred_locations"]))),
                    self._json_serialize(merge.get("education", self._json_deserialize(src_d["education"]))),
                    self._json_serialize(merge.get("projects", self._json_deserialize(src_d["projects"]))),
                    source_resume_id,
                    (src_d["version"] or 1) + 1,
                    merge.get("version_label"),
                    now,
                    now,
                ),
            )
            conn.commit()
            return new_id
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

    def update_jd_quality_score(self, jd_id: str, score: Optional[float],
                                checked_at: Optional[str] = None) -> None:
        """v2.1 M11: 写入 jds.quality_score + quality_checked_at。score=None 清缓存。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE jds SET quality_score = ?, quality_checked_at = ? WHERE id = ?",
                (score, checked_at, jd_id),
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
            cur = conn.execute(
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
            # v4 P0-模块 3: 同步写入 vec0 索引（仅 512 维 BGE 向量）
            self._maybe_insert_into_vec0(conn, cur.lastrowid, emb_blob, emb_dim)
            conn.commit()
        finally:
            conn.close()
        return chunk_id

    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict]) -> List[str]:
        ids = []
        conn = self._get_conn()
        try:
            vec0_writes: List[Tuple[int, Optional[bytes], Optional[int]]] = []
            for i, chunk in enumerate(chunks):
                chunk["jd_id"] = jd_id
                chunk["chunk_index"] = i
                chunk_id = chunk.get("id") or str(uuid.uuid4())
                emb_blob = self._embedding_to_blob(chunk.get("embedding"))
                emb_dim = chunk.get("embedding_dim")
                if emb_dim is None and isinstance(chunk.get("embedding"), (list, tuple)):
                    emb_dim = len(chunk["embedding"])
                cur = conn.execute(
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
                vec0_writes.append((cur.lastrowid, emb_blob, emb_dim))
            # v4 P0-模块 3: 一次性把 512 维 chunk 写进 vec0
            self._bulk_insert_into_vec0(conn, vec0_writes)
            conn.commit()
        finally:
            conn.close()
        return ids

    # ------------------------------------------------------------------
    # v4 P0-模块 3: vec0 双写辅助
    # ------------------------------------------------------------------
    def _maybe_insert_into_vec0(self, conn: sqlite3.Connection, rowid: int,
                                emb_blob: Optional[bytes], emb_dim: Optional[int]) -> None:
        """单 chunk 写 vec0；dim 不匹配或 vec0 不可用时静默跳过。"""
        if emb_blob is None or emb_dim != _BGE_DIM:
            return
        if not self._vec0_available(conn):
            return
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {_VEC0_TABLE}(rowid, embedding) VALUES (?, ?)",
                (rowid, emb_blob),
            )
        except sqlite3.Error as exc:
            logger.warning(f"vec0 insert skipped (rowid={rowid}): {exc}")

    def _bulk_insert_into_vec0(self, conn: sqlite3.Connection,
                                writes: List[Tuple[int, Optional[bytes], Optional[int]]]) -> None:
        """批量 chunks 写 vec0；静默跳过 dim 不匹配 / vec0 不可用。"""
        if not writes or not self._vec0_available(conn):
            return
        try:
            payloads: List[Tuple[int, bytes]] = []
            for rowid, blob, dim in writes:
                if blob is None or dim != _BGE_DIM:
                    continue
                payloads.append((rowid, blob))
            if payloads:
                conn.executemany(
                    f"INSERT OR REPLACE INTO {_VEC0_TABLE}(rowid, embedding) VALUES (?, ?)",
                    payloads,
                )
        except sqlite3.Error as exc:
            logger.warning(f"vec0 bulk insert skipped: {exc}")

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
        """v4 P0-模块 3: vec0 MATCH fast-path + numpy fallback.

        Selection rule:
        - vec0 虚拟表存在 + sqlite-vec 扩展已加载 + query 是 512-dim → vec0 path
        - 否则 → numpy 全表扫描（mock 测试 / 早期非 512 维 chunk / vec0 不可用）

        Chunk_type weighting + min_similarity cutoff live in
        ``services.retrieval_service.RetrievalService``. ``filter_position`` is a
        hard JOIN on ``jds.position_tag`` so cross-industry chunks for the same
        position (e.g. "产品经理" in both 互联网 and 快消) are co-retrieved.
        """
        import numpy as np

        conn = self._get_conn()
        try:
            # ---- 决定走 vec0 还是 numpy ----
            use_vec0 = (
                self._vec0_available(conn)
                and query_embedding is not None
                and len(query_embedding) == _BGE_DIM
            )

            if use_vec0:
                return self._vector_search_vec0(
                    conn, query_embedding, top_k,
                    filter_chunk_type=filter_chunk_type,
                    user_id=user_id,
                    filter_position=filter_position,
                )
            return self._vector_search_numpy(
                conn, query_embedding, top_k,
                filter_chunk_type=filter_chunk_type,
                user_id=user_id,
                filter_position=filter_position,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # v4 P0-模块 3: vector_search vec0 fast-path
    # ------------------------------------------------------------------
    def _vector_search_vec0(self, conn: sqlite3.Connection, query_embedding: List[float],
                             top_k: int, filter_chunk_type: Optional[str] = None,
                             user_id: Optional[str] = None,
                             filter_position: Optional[str] = None) -> List[Dict]:
        """vec0 MATCH → top-K rowids → JOIN knowledge_chunks + jds → Python 端过滤 → top_k.

        过取倍数：max(top_k * 20, 200)。vec0 MATCH 跟外层 WHERE 互斥，所以过滤必须放在
        vec0 召回之后。倍数是经验值，可调。
        """
        import sqlite_vec
        import numpy as np

        q_arr = np.asarray(query_embedding, dtype=np.float32)
        q_blob = sqlite_vec.serialize_float32(q_arr)

        # 1) vec0 过取 top-N
        overfetch = max(top_k * 20, 200)
        rows = conn.execute(
            f"SELECT rowid, distance FROM {_VEC0_TABLE} "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (q_blob, overfetch),
        ).fetchall()

        if not rows:
            return []

        # vec0 cosine distance ∈ [0, 2]；similarity = 1 - distance
        rowids: List[int] = []
        dist_map: Dict[int, float] = {}
        for rid, dist in rows:
            rowids.append(int(rid))
            dist_map[int(rid)] = float(dist)

        # 2) JOIN 主表 + jds；WHERE 过滤（deleted_at / embedding / chunk_type / user_id / position）
        placeholders = ",".join("?" * len(rowids))
        conditions = [
            "kc.rowid IN (" + placeholders + ")",
            "kc.deleted_at IS NULL",
            "kc.embedding IS NOT NULL",
        ]
        params: List[Any] = list(rowids)
        if filter_chunk_type:
            conditions.append("kc.chunk_type = ?"); params.append(filter_chunk_type)
        if user_id:
            conditions.append("kc.user_id = ?"); params.append(user_id)
        if filter_position:
            conditions.append("j.position_tag = ?"); params.append(filter_position)
        sql = (
            "SELECT kc.rowid AS kc_rowid, kc.*, j.industry_tag AS jd_industry_tag, "
            "j.function_tag AS jd_function_tag, j.position_tag AS jd_position_tag "
            "FROM knowledge_chunks kc "
            "LEFT JOIN jds j ON j.id = kc.jd_id "
            "WHERE " + " AND ".join(conditions)
        )
        rows_meta = conn.execute(sql, params).fetchall()

        # 3) 按 similarity 排序（vec0 已 distance ASC，但 JOIN + WHERE 后顺序可能变），取 top_k
        scored: List[Tuple[float, sqlite3.Row]] = []
        for row in rows_meta:
            rid = row["kc_rowid"]
            if rid not in dist_map:
                continue
            sim = 1.0 - dist_map[rid]
            scored.append((sim, row))
        scored.sort(key=lambda t: t[0], reverse=True)
        scored = scored[:top_k]

        results: List[Dict] = []
        for sim, row in scored:
            d = self._row_to_dict(row)
            d["keywords"] = self._json_deserialize(d.get("keywords"))
            d["heading_path"] = self._json_deserialize(d.get("heading_path", "[]"))
            d["embedding"] = None
            d["similarity"] = round(sim, 4)
            d.setdefault("metadata", {})
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # v4 P0-模块 3: vector_search numpy fallback（vec0 不可用时）
    # ------------------------------------------------------------------
    def _vector_search_numpy(self, conn: sqlite3.Connection, query_embedding: List[float],
                             top_k: int, filter_chunk_type: Optional[str] = None,
                             user_id: Optional[str] = None,
                             filter_position: Optional[str] = None) -> List[Dict]:
        """numpy cosine 全表扫描；保持 v2.1 行为不变以兼容非 512-dim / 老 chunk。"""
        import numpy as np

        conditions = ["kc.deleted_at IS NULL", "kc.embedding IS NOT NULL"]
        params: List[Any] = []
        if filter_chunk_type:
            conditions.append("kc.chunk_type = ?"); params.append(filter_chunk_type)
        if user_id:
            conditions.append("kc.user_id = ?"); params.append(user_id)
        if filter_position:
            conditions.append("j.position_tag = ?"); params.append(filter_position)
        sql = (
            "SELECT kc.rowid AS kc_rowid, kc.*, j.industry_tag AS jd_industry_tag, "
            "j.function_tag AS jd_function_tag, j.position_tag AS jd_position_tag "
            "FROM knowledge_chunks kc "
            "LEFT JOIN jds j ON j.id = kc.jd_id "
            "WHERE " + " AND ".join(conditions)
        )
        rows = conn.execute(sql, params).fetchall()

        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q)) or 1.0

        scored: List[Tuple[float, Dict]] = []
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
            conditions = ["kc.deleted_at IS NULL AND kc.chunk_text LIKE ?"]
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
                     error_type, error_message, metadata, user_id, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
                    data.get("user_id", "default"),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_llm_usage_today(self, user_id: Optional[str] = None) -> Dict[str, int]:
        conn = self._get_conn()
        try:
            sql = (
                "SELECT COUNT(*) AS calls, "
                "COALESCE(SUM(total_tokens), 0) AS tokens "
                "FROM llm_calls WHERE date(created_at) = date('now')"
            )
            params: List[Any] = []
            if user_id is not None:
                sql += " AND user_id = ?"
                params.append(user_id)
            row = conn.execute(sql, params).fetchone()
            return {"calls": int(row["calls"]), "tokens": int(row["tokens"])}
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

    # ==================== Flow A Drafts ====================

    def _deserialize_flow_a_draft(self, row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        d = self._row_to_dict(row)
        for field in ["section_data", "section_messages", "section_status", "generation_state"]:
            d[field] = self._json_deserialize(d.get(field))
            if d[field] == []:
                d[field] = {}
        return d

    def upsert_flow_a_draft(self, data: Dict[str, Any]) -> str:
        draft_id = data.get("id") or str(uuid.uuid4())
        now = datetime.now().isoformat()
        status = data.get("status", "draft")
        completed_at = data.get("completed_at")
        if status == "completed" and not completed_at:
            completed_at = now

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO flow_a_drafts
                    (id, user_id, status, industry, function, position,
                     current_step, current_section, section_data, section_messages,
                     section_status, generation_state, last_error, created_at,
                     updated_at, completed_at, deleted_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, flow_a_drafts.user_id),
                    status = excluded.status,
                    industry = COALESCE(excluded.industry, flow_a_drafts.industry),
                    function = COALESCE(excluded.function, flow_a_drafts.function),
                    position = COALESCE(excluded.position, flow_a_drafts.position),
                    current_step = excluded.current_step,
                    current_section = excluded.current_section,
                    section_data = excluded.section_data,
                    section_messages = excluded.section_messages,
                    section_status = excluded.section_status,
                    generation_state = excluded.generation_state,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at,
                    completed_at = COALESCE(excluded.completed_at, flow_a_drafts.completed_at),
                    deleted_at = excluded.deleted_at
                """,
                (
                    draft_id,
                    data.get("user_id", "default"),
                    status,
                    data.get("industry"),
                    data.get("function"),
                    data.get("position"),
                    data.get("current_step", "target"),
                    data.get("current_section"),
                    self._json_serialize(data.get("section_data", {})),
                    self._json_serialize(data.get("section_messages", {})),
                    self._json_serialize(data.get("section_status", {})),
                    self._json_serialize(data.get("generation_state", {})),
                    data.get("last_error"),
                    data.get("created_at", now),
                    now,
                    completed_at,
                    data.get("deleted_at"),
                ),
            )
            conn.commit()
            return draft_id
        finally:
            conn.close()

    def get_flow_a_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM flow_a_drafts WHERE id = ? AND deleted_at IS NULL",
                (draft_id,),
            ).fetchone()
            return self._deserialize_flow_a_draft(row)
        finally:
            conn.close()

    def get_latest_flow_a_draft(self, user_id: str = "default",
                                statuses: Optional[tuple[str, ...]] = None) -> Optional[Dict[str, Any]]:
        statuses = statuses or ("draft", "generating", "failed")
        placeholders = ",".join("?" for _ in statuses)
        conn = self._get_conn()
        try:
            row = conn.execute(
                f"""
                SELECT * FROM flow_a_drafts
                WHERE user_id = ?
                  AND deleted_at IS NULL
                  AND status IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, *statuses),
            ).fetchone()
            return self._deserialize_flow_a_draft(row)
        finally:
            conn.close()

    def abandon_flow_a_draft(self, draft_id: str) -> None:
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE flow_a_drafts
                SET status = 'abandoned', deleted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, draft_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ==================== Audit Logs ====================

    def insert_audit_log(self, data: Dict) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs
                    (user_id, action, target_table, target_id, status,
                     error_message, details)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("user_id", "default"),
                    data["action"],
                    data.get("target_table"),
                    data.get("target_id"),
                    data.get("status", "success"),
                    data.get("error_message"),
                    self._json_serialize(data.get("details")),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def list_audit_logs(self, user_id: Optional[str] = None,
                        action: Optional[str] = None,
                        target_table: Optional[str] = None,
                        limit: int = 100) -> List[Dict]:
        conn = self._get_conn()
        try:
            where = ["1=1"]
            params: List[Any] = []
            if user_id:
                where.append("user_id = ?")
                params.append(user_id)
            if action:
                where.append("action = ?")
                params.append(action)
            if target_table:
                where.append("target_table = ?")
                params.append(target_table)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT * FROM audit_logs
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return self._deserialize_all(rows, json_fields=["details"])
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

    # ==================== v3 M-rebuild-1: Structured JDs ====================

    def insert_jd_structured(self, data: Dict) -> int:
        """Insert a structured JD record (text/image/rag parsed).

        Required: ``source`` (``'text'``/``'image'``/``'rag'``). Optional:
        ``user_id`` (default ``'default'``), ``raw_text``, ``company``,
        ``title``, ``industry``, ``function``, ``level``,
        ``responsibilities`` (List[str]), ``requirements`` (List[str]).

        Returns the autoincrement ``jd_id``.
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO jd_structured
                   (user_id, source, raw_text, company, title, industry, function, level,
                    responsibilities, requirements)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (data.get("user_id", "default"), data["source"], data.get("raw_text"),
                 data.get("company"), data.get("title"), data.get("industry"),
                 data.get("function"), data.get("level"),
                 self._json_serialize(data.get("responsibilities", [])),
                 self._json_serialize(data.get("requirements", []))),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_jd_structured(self, jd_id: int) -> Optional[Dict]:
        """Fetch a structured JD by id; returns None if missing or soft-deleted."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM jd_structured WHERE jd_id = ? AND deleted_at IS NULL",
                (jd_id,),
            ).fetchone()
            if not row:
                return None
            return self._deserialize_all([row], ["responsibilities", "requirements"])[0]
        finally:
            conn.close()

    def list_jds_structured(self, user_id: str = "default",
                            source: Optional[str] = None,
                            limit: int = 100) -> List[Dict]:
        """List recent structured JDs, optionally filtered by source."""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM jd_structured WHERE user_id = ? AND deleted_at IS NULL"
            params: List[Any] = [user_id]
            if source:
                sql += " AND source = ?"
                params.append(source)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return self._deserialize_all(rows, ["responsibilities", "requirements"])
        finally:
            conn.close()

    # ==================== v3 M-rebuild-2: Rewrite History ====================

    def insert_rewrite_history(self, data: Dict) -> int:
        """Persist one rewrite run (mode A/B/A+B) with input/output snapshots.

        Required: ``resume_id``, ``mode`` (``'A'``/``'B'``/``'A+B'``). Optional:
        ``user_id`` (default ``'default'``), ``jd_id``, ``input_snapshot``
        (Dict), ``output_snapshot`` (Dict), ``rewrite_notes`` (Dict),
        ``user_edited`` (0/1, default 0).

        Returns the autoincrement ``rewrite_id``.
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO rewrite_history
                   (user_id, resume_id, jd_id, mode,
                    input_snapshot, output_snapshot, rewrite_notes, user_edited)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (data.get("user_id", "default"), data["resume_id"], data.get("jd_id"),
                 data["mode"],
                 self._json_serialize(data.get("input_snapshot", {})),
                 self._json_serialize(data.get("output_snapshot", {})),
                 self._json_serialize(data.get("rewrite_notes", {})),
                 data.get("user_edited", 0)),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def list_rewrite_history(self, resume_id: Optional[str] = None,
                             user_id: str = "default",
                             limit: int = 100) -> List[Dict]:
        """List recent rewrites, optionally filtered by resume, newest first."""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM rewrite_history WHERE user_id = ?"
            params: List[Any] = [user_id]
            if resume_id:
                sql += " AND resume_id = ?"
                params.append(resume_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return self._deserialize_all(
                rows, ["input_snapshot", "output_snapshot", "rewrite_notes"]
            )
        finally:
            conn.close()

    def mark_rewrite_user_edited(self, rewrite_id: int) -> None:
        """Set ``user_edited = 1`` after the user edits the rewrite output."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE rewrite_history SET user_edited = 1 WHERE rewrite_id = ?",
                (rewrite_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ==================== v3 M-rebuild-1: Resume Achievements Top-Level ====================

    def update_resume_achievements(self, resume_id: str, achievements: List[str]) -> None:
        """Update the top-level ``resumes.achievements`` JSON column."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE resumes SET achievements = ?, updated_at = ? WHERE id = ?",
                (self._json_serialize(achievements), datetime.now().isoformat(), resume_id),
            )
            conn.commit()
        finally:
            conn.close()
