@echo off
cd /d "%~dp0"
echo ========================================
echo    Job Hunter - 网页版
echo ========================================
echo.

echo [1/2] 检查依赖...
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo [提示] Streamlit 未安装，正在安装...
    pip install streamlit
)

echo.
echo [2/2] 启动网页版...
echo.
echo 网页版将在浏览器中打开！
echo.
echo 如果浏览器没有自动打开，请复制下方链接并访问：
echo http://localhost:8501
echo.
pause
streamlit run web_app.py
