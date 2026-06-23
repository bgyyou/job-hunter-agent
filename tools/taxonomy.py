# -*- coding: utf-8 -*-
"""读取 data/job_taxonomy.json 提供 industry → function → position 选择查询。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

_TAXONOMY_PATH = Path(__file__).parent.parent / "data" / "job_taxonomy.json"

_cache: Optional[Dict] = None


def _load() -> Dict:
    global _cache
    if _cache is None:
        with open(_TAXONOMY_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def list_industries() -> List[str]:
    """列出所有行业（一级分类）"""
    data = _load()
    return sorted(data.get("categories", {}).keys())


def list_functions(industry: str) -> List[str]:
    """列出某行业下的职能（二级分类）"""
    data = _load()
    industry_data = data.get("categories", {}).get(industry, {})
    return sorted(industry_data.get("职能", {}).keys())


def list_positions(industry: str, function: Optional[str] = None) -> List[str]:
    """列出某行业（可选职能）下的岗位（三级分类）"""
    data = _load()
    industry_data = data.get("categories", {}).get(industry, {}).get("职能", {})
    if function:
        return list(industry_data.get(function, {}).get("岗位", []))
    # 不指定职能，返回整个行业下的所有岗位（去重）
    all_positions = set()
    for func_data in industry_data.values():
        all_positions.update(func_data.get("岗位", []))
    return sorted(all_positions)
