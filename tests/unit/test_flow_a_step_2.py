# -*- coding: utf-8 -*-
"""v3 round-2: Flow A Step 2（渐进式披露表单）单测

按 update_plan.md §1.1：
- 默认最小集：1 段教育 + 1 段工作 + 0 段项目
- "成果数据"独立字段
- 技能/证书/语言/作品集折叠区
- 必填校验

M-v4-2 变更：
- _ensure_step2_form 不再从 legacy fa_section_data 兜底迁移
  （owner P0-004 决议：一次性硬切，不留 legacy 兜底）
- target_role 从 fa_jd_structured / fa_position 派生

覆盖（≥ 6 条）：
1. _ensure_step2_form 默认初始化（1 段教育 + 1 段工作 + 0 段项目）
2. _ensure_step2_form target_role 从 fa_jd_structured 派生
3. _ensure_step2_form 已存在则复用
4. _validate_step2_form 缺姓名 → 报错
5. _validate_step2_form 缺手机+邮箱 → 报错
6. _validate_step2_form 缺教育学校/学历 → 报错
7. _validate_step2_form 缺工作公司/岗位 → 报错
8. _validate_step2_form 全部填齐 → OK
9. step2_form_to_resume 转换字段（achievements 拆行 + skills 拆逗号 + 顶层字段）
10. step2_form_to_resume 0 段工作 + 0 段项目（边缘场景）
"""
from __future__ import annotations

import importlib

page_mod_1 = importlib.import_module('pages.04_📝_Flow_A_Step2')

import pytest


def _import_web_app():
    return importlib.import_module("web_app")


@pytest.fixture
def web_app_mod():
    return _import_web_app()


# ============================================================
# _ensure_step2_form：默认初始化 + legacy 迁移
# ============================================================

class TestEnsureStep2Form:
    def test_default_minimum(self, web_app_mod, monkeypatch):
        """首次进入 Step 2 → 1 段教育 + 1 段工作 + 0 段项目。"""
        state = _FakeSession()
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        form = page_mod_1._ensure_step2_form()
        assert len(form["education"]) == 1
        assert len(form["work"]) == 1
        assert len(form["projects"]) == 0
        # 教育 / 工作 模板字段全空
        assert form["education"][0]["school"] == ""
        assert form["work"][0]["company"] == ""
        assert form["work"][0]["end_date"] == "至今"
        # 折叠区字段存在
        assert "skills_text" in form
        assert "languages_text" in form
        assert "portfolio" in form

    def test_target_role_from_fa_jd_structured(self, web_app_mod, monkeypatch):
        """target_role 应从 fa_jd_structured.title 派生（不再走 legacy）。"""
        state = _FakeSession()
        state["fa_jd_structured"] = {"title": "AI 产品经理"}
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        form = page_mod_1._ensure_step2_form()
        assert form["basic"]["target_role"] == "AI 产品经理"
        # 非遗留：basic 字段全空，没有任何 fa_section_data 兜底
        assert form["basic"]["name"] == ""
        assert form["basic"]["phone"] == ""
        assert form["skills_text"] == ""

    def test_target_role_fallback_to_fa_position(self, web_app_mod, monkeypatch):
        """fa_jd_structured 缺时回退 fa_position。"""
        state = _FakeSession()
        state["fa_position"] = "Data Scientist"
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        form = page_mod_1._ensure_step2_form()
        assert form["basic"]["target_role"] == "Data Scientist"

    def test_reuse_existing(self, web_app_mod, monkeypatch):
        """已存在 → 复用，不重新初始化。"""
        state = _FakeSession()
        state["fa_step2_form"] = {"basic": {"name": "已存在"}, "_marker": True}
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        form = page_mod_1._ensure_step2_form()
        assert form["basic"]["name"] == "已存在"
        assert form["_marker"] is True


# ============================================================
# _validate_step2_form：必填校验
# ============================================================

class TestValidateStep2Form:
    def _form(self, **overrides):
        form = {
            "basic": {
                "name": "张三", "phone": "13800138000", "email": "z@z.com",
                "target_role": "PM",
            },
            "education": [{"school": "北大", "degree": "本科", "major": "CS",
                          "start_year": "2020", "end_year": "2024", "gpa": ""}],
            "work": [{"company": "字节", "title": "PM",
                     "start_date": "2024.06", "end_date": "至今",
                     "description": "做产品", "achievements_text": "促成 200 单"}],
        }
        form["basic"].update(overrides.pop("basic", {}))
        if "edu_school" in overrides:
            form["education"][0]["school"] = overrides.pop("edu_school")
        if "edu_degree" in overrides:
            form["education"][0]["degree"] = overrides.pop("edu_degree")
        if "w_company" in overrides:
            form["work"][0]["company"] = overrides.pop("w_company")
        if "w_title" in overrides:
            form["work"][0]["title"] = overrides.pop("w_title")
        return form

    def test_missing_name(self, web_app_mod):
        form = self._form()
        form["basic"]["name"] = ""
        err = page_mod_1._validate_step2_form(form)
        assert err and "姓名" in err

    def test_missing_phone_and_email(self, web_app_mod):
        form = self._form()
        form["basic"]["phone"] = ""
        form["basic"]["email"] = ""
        err = page_mod_1._validate_step2_form(form)
        assert err and ("手机" in err or "邮箱" in err)

    def test_missing_edu_school(self, web_app_mod):
        form = self._form(edu_school="")
        err = page_mod_1._validate_step2_form(form)
        assert err and "教育" in err

    def test_missing_edu_degree(self, web_app_mod):
        form = self._form(edu_degree="")
        err = page_mod_1._validate_step2_form(form)
        assert err and "教育" in err

    def test_missing_work_company(self, web_app_mod):
        form = self._form(w_company="")
        err = page_mod_1._validate_step2_form(form)
        assert err and "工作" in err

    def test_missing_work_title(self, web_app_mod):
        form = self._form(w_title="")
        err = page_mod_1._validate_step2_form(form)
        assert err and "工作" in err

    def test_valid_form_passes(self, web_app_mod):
        form = self._form()
        err = page_mod_1._validate_step2_form(form)
        assert err is None


# ============================================================
# step2_form_to_resume：form → resume dict
# ============================================================

class TestStep2FormToResume:
    def test_basic_fields(self, web_app_mod):
        form = {
            "basic": {
                "name": "张三", "phone": "13800138000", "email": "z@z.com",
                "location": "北京", "target_role": "AI 产品经理", "gender": "",
            },
            "education": [], "work": [], "projects": [],
            "skills_text": "", "certifications_text": "", "languages_text": "",
            "portfolio": "",
        }
        r = page_mod_1.step2_form_to_resume(form)
        assert r["name"] == "张三"
        assert r["phone"] == "13800138000"
        assert r["email"] == "z@z.com"
        assert r["target_roles"] == ["AI 产品经理"]

    def test_work_achievements_split_lines(self, web_app_mod):
        form = {
            "basic": {"name": "X", "phone": "1", "email": "", "target_role": ""},
            "education": [], "work": [{
                "company": "字节", "title": "PM",
                "start_date": "2024.06", "end_date": "至今",
                "description": "做产品",
                "achievements_text": "促成 200 单成交\nGMV 120 万\n团队规模 3→10",
            }], "projects": [],
            "skills_text": "", "certifications_text": "", "languages_text": "",
            "portfolio": "",
        }
        r = page_mod_1.step2_form_to_resume(form)
        assert len(r["experience"]) == 1
        assert r["experience"][0]["achievements"] == [
            "促成 200 单成交", "GMV 120 万", "团队规模 3→10",
        ]

    def test_skills_split_comma_and_newline(self, web_app_mod):
        form = {
            "basic": {"name": "X", "phone": "1", "email": "", "target_role": ""},
            "education": [], "work": [], "projects": [],
            "skills_text": "Python, LLM\nRAG, SQL",
            "certifications_text": "PMP, AWS",
            "languages_text": "中文, 英语",
            "portfolio": "github.com/x",
        }
        r = page_mod_1.step2_form_to_resume(form)
        assert r["skills"] == ["Python", "LLM", "RAG", "SQL"]
        assert r["certifications"] == ["PMP", "AWS"]
        assert r["languages"] == ["中文", "英语"]
        assert r["portfolio"] == "github.com/x"

    def test_projects_passed_through(self, web_app_mod):
        form = {
            "basic": {"name": "X", "phone": "1", "email": "", "target_role": ""},
            "education": [], "work": [], "projects": [{
                "name": "AI Agent", "role": "PM", "start_date": "2024", "end_date": "至今",
                "description": "D", "contribution": "C",
                "achievements_text": "达成 1000 DAU",
            }],
            "skills_text": "", "certifications_text": "", "languages_text": "",
            "portfolio": "",
        }
        r = page_mod_1.step2_form_to_resume(form)
        assert len(r["projects"]) == 1
        assert r["projects"][0]["name"] == "AI Agent"
        assert r["projects"][0]["achievements"] == ["达成 1000 DAU"]

    def test_empty_work_and_projects(self, web_app_mod):
        form = {
            "basic": {"name": "X", "phone": "1", "email": "", "target_role": ""},
            "education": [], "work": [], "projects": [],
            "skills_text": "", "certifications_text": "", "languages_text": "",
            "portfolio": "",
        }
        r = page_mod_1.step2_form_to_resume(form)
        assert r["experience"] == []
        assert r["projects"] == []
        assert r["education"] == []


# ============================================================
# helpers
# ============================================================

class _FakeSession(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v
