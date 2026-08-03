"""v3 M-rebuild-1: schema + CRUD 集成测试

覆盖 3 张新表（jd_structured / rewrite_history / interview_questions）
+ 7 个新 CRUD 接口 + resumes.achievements 顶层字段持久化 + JSON 列双向序列化。

注：rag_industry_function 表 017 迁移已 DROP，相关 CRUD 断言从本文件移除。
"""
import pytest
import json


class TestV3TablesExist:
    """3 张 v3 表真实存在于 SQLite（rag_industry_function 017 已 DROP）。"""

    def test_jd_structured_table(self, tmp_db):
        rows = tmp_db._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jd_structured'"
        ).fetchall()
        assert rows, "jd_structured 表未创建"

    def test_rewrite_history_table(self, tmp_db):
        rows = tmp_db._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rewrite_history'"
        ).fetchall()
        assert rows, "rewrite_history 表未创建"

    def test_interview_questions_table(self, tmp_db):
        rows = tmp_db._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='interview_questions'"
        ).fetchall()
        assert rows, "interview_questions 表未创建（M-rebuild-4 暂未用）"

    def test_resumes_achievements_column_exists(self, tmp_db):
        """resumes.achievements 顶层字段存在（M-rebuild-1）。"""
        cols = {
            r[1] for r in tmp_db._get_conn().execute(
                "PRAGMA table_info(resumes)"
            ).fetchall()
        }
        assert "achievements" in cols, "resumes.achievements 列未创建"


class TestJDSructuredCRUD:
    """jd_structured：3 个方法（insert / get / list）。"""

    def test_insert_and_get(self, tmp_db):
        jd_id = tmp_db.insert_jd_structured({
            "source": "text",
            "company": "字节跳动",
            "title": "AI 产品经理",
            "industry": "互联网",
            "function": "产品",
            "level": "senior",
            "responsibilities": ["AI 产品规划", "跨部门协调"],
            "requirements": ["3年以上 AI 经验", "本科及以上"],
        })
        assert isinstance(jd_id, int) and jd_id > 0

        jd = tmp_db.get_jd_structured(jd_id)
        assert jd is not None
        assert jd["source"] == "text"
        assert jd["company"] == "字节跳动"
        assert jd["responsibilities"] == ["AI 产品规划", "跨部门协调"]
        assert jd["requirements"] == ["3年以上 AI 经验", "本科及以上"]

    def test_list_filtered_by_source(self, tmp_db):
        tmp_db.insert_jd_structured({"source": "text", "title": "A"})
        tmp_db.insert_jd_structured({"source": "image", "title": "B"})
        tmp_db.insert_jd_structured({"source": "text", "title": "C"})

        all_jds = tmp_db.list_jds_structured()
        assert len(all_jds) >= 3

        text_only = tmp_db.list_jds_structured(source="text")
        assert all(j["source"] == "text" for j in text_only)

    def test_get_missing_returns_none(self, tmp_db):
        """不存在的 jd_id → None。"""
        assert tmp_db.get_jd_structured(999999) is None


class TestRewriteHistoryCRUD:
    """rewrite_history：3 个方法（insert / list / mark_user_edited）。"""

    def test_insert_and_list(self, tmp_db):
        # 先建一个 resume 用于外键关联（虽然实际 SQL 没强制 FK，但语义需要）
        resume_id = tmp_db.insert_resume({"name": "测试", "user_id": "default"})

        rid = tmp_db.insert_rewrite_history({
            "resume_id": resume_id,
            "mode": "A",
            "jd_id": None,
            "input_snapshot": {"name": "张三"},
            "output_snapshot": {"rewrites": [{"section": "experience"}]},
            "rewrite_notes": {"mode_a_reason": "对接 AI 能力词"},
        })
        assert isinstance(rid, int) and rid > 0

        rows = tmp_db.list_rewrite_history(resume_id=resume_id)
        assert len(rows) >= 1
        # JSON 列应被反序列化回 Python 对象
        assert rows[0]["input_snapshot"] == {"name": "张三"}
        assert rows[0]["output_snapshot"]["rewrites"][0]["section"] == "experience"

    def test_mark_user_edited(self, tmp_db):
        resume_id = tmp_db.insert_resume({"name": "测试"})
        rid = tmp_db.insert_rewrite_history({
            "resume_id": resume_id,
            "mode": "B",
            "output_snapshot": {"templates": []},
        })
        tmp_db.mark_rewrite_user_edited(rid)

        rows = tmp_db.list_rewrite_history(resume_id=resume_id)
        target = next(r for r in rows if r["rewrite_id"] == rid)
        assert target["user_edited"] == 1


class TestResumeAchievementsCRUD:
    """resumes.achievements 顶层字段 + update_resume_achievements()。"""

    def test_update_achievements_persists(self, tmp_db):
        resume_id = tmp_db.insert_resume({"name": "张三"})
        tmp_db.update_resume_achievements(resume_id, ["促成 200 单成交", "GMV 120 万"])

        loaded = tmp_db.get_resume(resume_id)
        assert loaded["achievements"] == ["促成 200 单成交", "GMV 120 万"]

    def test_update_achievements_overwrites(self, tmp_db):
        """二次 update 应覆盖而不是追加。"""
        resume_id = tmp_db.insert_resume({"name": "李四"})
        tmp_db.update_resume_achievements(resume_id, ["A", "B"])
        tmp_db.update_resume_achievements(resume_id, ["C"])
        loaded = tmp_db.get_resume(resume_id)
        assert loaded["achievements"] == ["C"]

    def test_default_achievements_empty_list(self, tmp_db):
        """新简历不显式调 update 时 achievements 应为空列表。"""
        resume_id = tmp_db.insert_resume({"name": "王五"})
        loaded = tmp_db.get_resume(resume_id)
        # 默认值 '[]' → 反序列化为 []
        assert loaded["achievements"] == []


class TestJSONRoundTrip:
    """JSON 列双向序列化正确性。"""

    def test_jd_structured_json_lists(self, tmp_db):
        """List[str] 入库 → 出库仍为 list。"""
        jd_id = tmp_db.insert_jd_structured({
            "source": "rag",
            "responsibilities": ["A", "B", "C"],
            "requirements": ["X", "Y"],
        })
        loaded = tmp_db.get_jd_structured(jd_id)
        assert isinstance(loaded["responsibilities"], list)
        assert loaded["responsibilities"] == ["A", "B", "C"]

    def test_rewrite_history_snapshot_dict(self, tmp_db):
        """Dict 入库 → 出库仍为 dict。"""
        resume_id = tmp_db.insert_resume({"name": "测试"})
        rid = tmp_db.insert_rewrite_history({
            "resume_id": resume_id,
            "mode": "A+B",
            "input_snapshot": {"k": "v", "list": [1, 2, 3]},
            "output_snapshot": {"rewrites": [{"section": "exp"}]},
        })
        rows = tmp_db.list_rewrite_history(resume_id=resume_id)
        target = next(r for r in rows if r["rewrite_id"] == rid)
        assert target["input_snapshot"]["list"] == [1, 2, 3]
        assert isinstance(target["output_snapshot"], dict)