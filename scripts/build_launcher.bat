@echo off
REM 一键重建 JobHunter.exe 的 Windows 批处理。
REM
REM 用法（cmd / Git Bash / 双击均可）：
REM   scripts\build_launcher.bat
REM
REM 输出：dist\JobHunter.exe

setlocal

cd /d "%~dp0\.."

echo ========================================
echo   重建 JobHunter.exe
echo ========================================
echo.

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [1/3] 安装 pyinstaller...
    pip install pyinstaller || goto :fail
)

echo [2/3] 清理旧 build/dist...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] pyinstaller --onefile ...
pyinstaller --onefile --name JobHunter --distpath dist scripts\jobhunter_launcher.py
if errorlevel 1 goto :fail

echo.
echo ========================================
echo   [OK] 产物: dist\JobHunter.exe
echo   双击即可在浏览器中打开 JobHunter。
echo ========================================
exit /b 0

:fail
echo.
echo [FAIL] 构建失败。请检查上面报错。
exit /b 1
