@echo off
setlocal
cd /d "%~dp0python"

set QT_LOGGING_RULES=qt.multimedia.ffmpeg*=false;*.debug=false
set QT_FFMPEG_DEBUG=0

echo Starting ComeCut Python GUI...
.\venv\Scripts\python.exe -m comecut_py gui

if %ERRORLEVEL% neq 0 (
    echo.
    echo Application failed with error code %ERRORLEVEL%
    pause
)
endlocal
