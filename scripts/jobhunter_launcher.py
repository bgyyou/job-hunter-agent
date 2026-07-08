# -*- coding: utf-8 -*-
"""JobHunter 一键启动器：子进程跑 streamlit → 轮询就绪 → 自动开浏览器。

支持两种运行模式：
  1. python scripts/jobhunter_launcher.py — 仓库内开发用
  2. 双击 JobHunter.exe — pyinstaller 打包后 frozen 模式（frozen=True）

行为：
  - 启动 streamlit run web_app.py（无头模式，避免浏览器抢开）
  - 轮询 http://localhost:8501 等到 200 OK（最多 60 秒）
  - 用 webbrowser.open 打开默认浏览器
  - 阻塞等 streamlit 子进程退出；Ctrl+C 也安全
  - streamlit 端口被占用 → 用 streamlit 自动分配的另一个端口（轮询时探测 _healthz）
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Windows console 默认 GBK，emoji / 箭头会爆。先 reconfigure stdout/stderr 到 utf-8。
# frozen pyinstaller 模式要绕过 io.TextIOWrapper 重新设置。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


DEFAULT_PORT = int(os.environ.get("JOBHUNTER_PORT", "8501"))
READY_TIMEOUT = 60.0  # seconds
POLL_INTERVAL = 0.5


def find_python_for_streamlit() -> str:
    """返回用来跑 `streamlit` 的可执行路径。

    - 未 frozen：直接用当前 sys.executable（包含 venv 时也对）
    - frozen (pyinstaller .exe)：当前 sys.executable 是 .exe 自己 — 不能用它跑 -m streamlit。
      退回 PATH 上的 python / py launcher。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    # frozen: 试 PATH 上的 python / py
    import shutil

    for candidate in ("python", "python3", "py"):
        path = shutil.which(candidate)
        if path:
            return path
    # 最后兜底
    return sys.executable


def find_python_for_streamlit() -> str:
    """返回用来跑 `streamlit` 的可执行路径。

    - 未 frozen：直接用当前 sys.executable（包含 venv 时也对）
    - frozen (pyinstaller .exe)：当前 sys.executable 是 .exe 自己 — 不能用它跑 -m streamlit。
      退回 PATH 上的 python / py launcher。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    # frozen: 试 PATH 上的 python / py
    import shutil

    for candidate in ("python", "python3", "py"):
        path = shutil.which(candidate)
        if path:
            return path
    # 最后兜底
    return sys.executable


def is_server_ready(url: str, timeout: float = 2.0) -> bool:
    """HTTP HEAD localhost:port 是否有响应。streamlit 启动中可能返 503，
    只要连得上且拿到 HTTP 响应（任意 status code），就算"服务在"。
    网络层连接失败 / 超时才返 False。"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 100 <= int(getattr(resp, "status", 0)) < 600
    except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, socket.timeout, OSError):
        return False


def parse_streamlit_url(output: str, default_port: int) -> int:
    """从 streamlit 启动输出里抓 'Network URL: http://...:PORT' 的端口。"""
    import re

    m = re.search(r"https?://[^\s:]+:(\d+)", output)
    if m:
        return int(m.group(1))
    return default_port


def find_web_app() -> Path | None:
    """找 web_app.py 路径。优先级：

    1. cwd（用户 cd 到项目再双击）
    2. exe 同目录（pyinstaller 默认 out）
    3. 项目根（git 仓库布局时）
    """
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd() / "web_app.py")
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "web_app.py")
        candidates.append(exe_dir.parent / "web_app.py")  # dist/JobHunter.exe → 上级
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "web_app.py")

    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def get_project_root(web_app_path: Path) -> Path:
    """项目根 = web_app.py 的所在目录。"""
    return web_app_path.parent


def main() -> int:
    print("=" * 56)
    print("  JobHunter 启动器（Web 前后端）")
    print("=" * 56)

    web_app = find_web_app()
    if web_app is None:
        print("[ERROR] 未找到 web_app.py。")
        print("        请在本项目根目录运行本程序（即与 web_app.py 同目录）。")
        try:
            input("\n按 Enter 退出...")
        except EOFError:
            pass
        return 1

    project_root = get_project_root(web_app)

    # v2.1 P2-1 阶段一：internal beta 模式（双击 .exe 直接用）
    # 把 internal_keys.json 里的 key 注入子进程 env，让 streamlit 起来就能调 LLM。
    subproc_env = os.environ.copy()
    try:
        sys.path.insert(0, str(project_root))
        from config.internal_keys import apply_internal_keys
        applied, src = apply_internal_keys()
        if applied:
            print(f"[0/3] Internal beta mode: LLM key loaded from {src}")
            # 把已注入的 env var 复制给 streamlit 子进程
            for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
                if os.environ.get(k):
                    subproc_env[k] = os.environ[k]
    except Exception as exc:
        print(f"[WARN] internal_keys helper load failed: {exc}")

    # 调用 streamlit。
    # - 未 frozen: 用 sys.executable (含 venv 那个 python)
    # - frozen: 退回 PATH 上的 python/py，因为 sys.executable 是 .exe 自己
    py_exe = find_python_for_streamlit()
    cmd = [
        py_exe,
        "-m", "streamlit", "run", str(web_app),
        "--server.port", str(DEFAULT_PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.enableCORS", "false",
    ]
    print(f"[1/3] 启动 streamlit: {' '.join(cmd)}")
    print(f"      cwd = {project_root}")

    # CREATE_NEW_CONSOLE 使点击时 streamlit log 可看到；
    # 在 frozen exe 下其实不用，用 PIPE 抓出只看端口。
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        env=subproc_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # 同步读取 streamlit 控制台输出，用于抓取实际端口、以及警告错误。
    detected_port = DEFAULT_PORT
    started = False

    print(f"[2/3] 等待服务就绪（{READY_TIMEOUT:.0f} 秒超时）...")

    def _read_some():
        if proc.stdout is None:
            return ""
        # 读一点不阻塞，超时 200ms
        import select

        try:
            # Windows 上 select 只对 socket 有效、不适用于 named pipe。
            # 改用线程后台读。
            return ""
        except Exception:
            return ""

    # 简化：让 streamlit 输出业只在后台读，主线程走轮询。
    import threading

    def _drain():
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            nonlocal detected_port
            print(f"  [streamlit] {line.rstrip()}")
            detected_port = parse_streamlit_url(line, DEFAULT_PORT)

    drainer = threading.Thread(target=_drain, daemon=True)
    drainer.start()

    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"\n[ERROR] streamlit 进程退出，code={proc.returncode}")
            return 1
        # 优先试默认端口；不崩为能跳到其他端口
        urls = [f"http://localhost:{DEFAULT_PORT}", f"http://localhost:{detected_port}"]
        if any(is_server_ready(u) for u in urls):
            port = detected_port if is_server_ready(f"http://localhost:{detected_port}") else DEFAULT_PORT
            url = f"http://localhost:{port}"
            print("[3/3] 服务就绪：{url}")
            print("      正在打开默认浏览器...")
            try:
                webbrowser.open(url)
            except Exception as exc:
                print(f"      [WARN] 自动打开浏览器失败：{exc}")
                print(f"      请手动访问：{url}")
            print()
            print("[OK] JobHunter 已启动。要停止服务，请直接关闭本窗口。")
            try:
                proc.wait()
            except KeyboardInterrupt:
                print("\n收到 Ctrl+C，正在停止 streamlit...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return proc.returncode or 0
        time.sleep(POLL_INTERVAL)

    print(f"\n[TIMEOUT] {READY_TIMEOUT:.0f} 秒内未检测到服务就绪。")
    proc.terminate()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断。")
        sys.exit(130)
