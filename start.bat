@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Lingxing ERP Automation Framework ===
echo Starting GUI...
python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Launch failed with code: %errorlevel%
    pause
)
