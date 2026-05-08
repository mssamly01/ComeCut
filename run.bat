@echo off
setlocal
cd /d "%~dp0python"

set QT_LOGGING_RULES=qt.multimedia.ffmpeg*=false;*.debug=false
set QT_FFMPEG_DEBUG=0
set QT_FFMPEG_DECODING_HW_DEVICE_TYPES=,
set QT_DISABLE_HW_TEXTURES_CONVERSION=1

echo Starting ComeCut Python GUI...
.\venv\Scripts\python.exe -m comecut_py gui

if %ERRORLEVEL% neq 0 (
    echo.
    echo Application failed with error code %ERRORLEVEL%
    pause
)
endlocal
