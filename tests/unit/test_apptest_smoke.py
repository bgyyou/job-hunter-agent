"""AppTest 依赖烟测 — 验证 streamlit.testing.v1.AppTest 在真 streamlit 下可 import。

历史：R13b-prep（2026-08-04）发现 streamlit 1.57.0 + starlette 0.38.6 组合下
streamlit.web.server.starlette.starlette_app 在 import 阶段就抛 ImportError
（starlette 0.40 才引入 DEFAULT_EXCLUDED_CONTENT_TYPES）。修复路径：
锁 streamlit>=1.30,<1.60 + pip-compile 让 starlette 自动升级到 1.3.1 +
升 fastapi 到 0.141（与 starlette 1.x 兼容）。本测试作为该依赖的"哨兵"，
CI 任意一次回归到旧版本都会红。

实现说明：tests/conftest.py 用 _StubEverything 把 streamlit 整个 mock 掉以
加速测试。我们必须在 subprocess 里跑一段干净 Python 才能验证真 streamlit。
subprocess 隔离 stub/conftest，让真模块走默认 import 链。
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_in_clean_subprocess(snippet: str) -> subprocess.CompletedProcess:
    """在干净 Python 子进程跑一段代码，绕开 conftest 的 streamlit stub。"""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def test_apptest_import_works() -> None:
    """干净 Python 下 streamlit.testing.v1.AppTest 必须能 import。"""
    proc = _run_in_clean_subprocess(
        """
        from streamlit.testing.v1 import AppTest
        assert AppTest is not None
        print("OK")
        """
    )
    assert proc.returncode == 0, (
        f"AppTest import failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_apptest_can_load_main_entry() -> None:
    """AppTest.from_file(web_app.py) 必须在干净 Python 下能加载主入口。"""
    proc = _run_in_clean_subprocess(
        """
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        web_app = Path("web_app.py").resolve()
        assert web_app.exists(), f"web_app.py not found at {web_app}"
        at = AppTest.from_file(str(web_app))
        assert at is not None
        assert at._script_path == str(web_app)
        print("OK")
        """
    )
    assert proc.returncode == 0, (
        f"AppTest.from_file failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_streamlit_and_starlette_versions_compatible() -> None:
    """硬约束：streamlit 与 starlette 必须满足 streamlit 1.58 的 API 要求。

    streamlit 1.58 在 starlette_gzip_middleware.py 引用
    starlette.middleware.gzip.DEFAULT_EXCLUDED_CONTENT_TYPES（starlette>=0.40）。
    若回到 starlette<0.40 或 streamlit<1.30，import 阶段即失败。
    """
    proc = _run_in_clean_subprocess(
        """
        import starlette
        import streamlit

        s = tuple(map(int, streamlit.__version__.split(".")[:2]))
        assert s >= (1, 30), (
            f"streamlit {streamlit.__version__} < 1.30 (DEFAULT_EXCLUDED_CONTENT_TYPES regression)"
        )

        parts = starlette.__version__.split(".")
        major, minor = int(parts[0]), int(parts[1])
        assert (major == 0 and minor >= 40) or major >= 1, (
            f"starlette {starlette.__version__} < 0.40 (DEFAULT_EXCLUDED_CONTENT_TYPES missing)"
        )
        print("OK")
        """
    )
    assert proc.returncode == 0, (
        f"version compat check failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "OK" in proc.stdout