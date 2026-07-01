@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Lingxing Element Collector V11 ===
python debug_elements-V11.py --cdp http://127.0.0.1:18800
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Exit code: %errorlevel%
    pause
)
