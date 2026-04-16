@echo off
echo.
echo ================================================
echo   NRC Market Intelligence -- Local Server
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b
)

:: Prompt for API key if not set
if "%ANTHROPIC_API_KEY%"=="" (
    set /p ANTHROPIC_API_KEY="Enter Anthropic API key (sk-ant-...): "
)

echo.
echo Checking dependencies...
pip install anthropic requests beautifulsoup4 flask flask-cors weasyprint -q

echo.
echo Starting server at http://localhost:5050
echo Keep this window open. Press Ctrl+C to stop.
echo.

python scripts\server.py
pause
