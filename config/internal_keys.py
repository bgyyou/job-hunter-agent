"""Internal Beta LLM Key 配置（v2.1 P2-1 阶段一）

解决内测用户门槛：让 .exe 双击即可用，不需要 .env。

设计：
- .exe 同目录（frozen）或项目根（dev）放 `internal_keys.json`
- 文件存在 → 把 api_key / base_url / model 注入 os.environ
- pydantic Settings 看到 os.environ 就用，不读 .env
- 文件不存在 → 完全不影响现有流程（`.env` / 向导照常）

JSON 结构（最小）：
{
    "api_key": "PUT-YOUR-REAL-KEY-HERE",
    "base_url": "https://...",
    "model": "..."
}

注意：
- 文件不进 git（已加 .gitignore）
- Key 明文 — 仅内测用，真上线要走 SaaS 鉴权
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger

# 优先级：环境变量 > .env > internal_keys.json
ENV_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")


def _candidate_paths() -> list[Path]:
    """返回 internal_keys.json 的多个候选路径，按优先级排。

    1. env var JOBHUNTER_INTERNAL_KEYS（测试时方便覆盖）
    2. .exe 同目录（frozen pyinstaller）
    3. .exe 上一级（dist/JobHunter.exe → 上一级是项目相关位置）
    4. 项目根（dev mode）
    5. data/internal_keys.json（项目内，不进 git）
    """
    paths: list[Path] = []

    explicit = os.environ.get("JOBHUNTER_INTERNAL_KEYS")
    if explicit:
        paths.append(Path(explicit))

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        paths.append(exe_dir / "internal_keys.json")
        paths.append(exe_dir.parent / "internal_keys.json")

    project_root = Path(__file__).resolve().parent.parent
    paths.append(project_root / "internal_keys.json")
    paths.append(project_root / "data" / "internal_keys.json")

    return paths


def _read_internal_keys(path: Path) -> Optional[dict]:
    """读 JSON。失败返回 None（容忍各种损坏，但不抛）。"""
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            logger.warning(f"internal_keys.json at {path} is not a JSON object, ignored")
            return None
        return data
    except Exception as exc:
        logger.warning(f"Failed to read {path}: {exc}")
        return None


def is_internal_beta_active() -> bool:
    """判断 internal beta 模式是否启用。

    返回 True 当且仅当：
    - internal_keys.json 文件存在且包含有效 api_key
    - LLM_API_KEY 环境变量还没被设置（避免覆盖用户的真实配置）
    """
    # 已经配过 → 不是"internal fallback"场景
    existing = (os.environ.get("LLM_API_KEY") or "").strip()
    if existing and existing != "your_api_key_here":
        return False

    for path in _candidate_paths():
        data = _read_internal_keys(path)
        if data and (data.get("api_key") or "").strip():
            return True
    return False


def apply_internal_keys(force: bool = False) -> Tuple[bool, Optional[Path]]:
    """把 internal_keys.json 的字段注入 os.environ。

    Args:
        force: True 时，即使 LLM_API_KEY 已经设置也覆盖（用于 launcher 显式覆盖）

    Returns:
        (applied, source_path) — applied 为 True 表示本次注入了。
        若 LLM_API_KEY 已存在且 force=False，返 (False, None) 且不动任何东西。
    """
    existing = (os.environ.get("LLM_API_KEY") or "").strip()
    if existing and existing != "your_api_key_here" and not force:
        return False, None

    for path in _candidate_paths():
        data = _read_internal_keys(path)
        if not data:
            continue
        api_key = (data.get("api_key") or "").strip()
        if not api_key:
            continue
        base_url = (data.get("base_url") or "").strip() or "https://apihub.agnes-ai.com/v1"
        model = (data.get("model") or "").strip() or "agnes-2.0-flash"

        os.environ["LLM_API_KEY"] = api_key
        os.environ["LLM_BASE_URL"] = base_url
        os.environ["LLM_MODEL"] = model

        logger.info(f"Internal beta mode active — LLM key loaded from {path}")
        return True, path

    return False, None
