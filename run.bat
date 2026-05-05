@echo off
setlocal
cd /d "%~dp0python"

echo Starting ComeCut Python GUI...
.\venv\Scripts\python.exe -m comecut_py gui

if %ERRORLEVEL% neq 0 (
    echo.
    echo Application failed with error code %ERRORLEVEL%
    pause
)
endlocal
