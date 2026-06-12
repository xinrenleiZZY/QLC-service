@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Lingxing Batch Create Keywords
echo   Current Dir: %CD%
echo ========================================
echo.
echo Starting...
python .\start_browser.py
echo.
echo ========================================
echo Process Finished!
echo ========================================
pause